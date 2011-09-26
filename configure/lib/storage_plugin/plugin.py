
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

import settings
from collections_24 import defaultdict
from django.db import transaction

from configure.models import StorageResourceRecord
from configure.lib.storage_plugin.resource import StorageResource, LocalId, GlobalId
from configure.lib.storage_plugin.log import storage_plugin_log

class ResourceNotFound(Exception):
    pass

class StoragePlugin(object):
    def __init__(self):
        from configure.lib.storage_plugin import storage_plugin_manager
        self._handle = storage_plugin_manager.register_plugin(self)

        # Resource cache is a map of StorageResourceRecord PK to 
        # StorageResource instance, including everything that's 
        # registered by this instance of the plugin.

        self._resource_cache = {}
        # TODO: give each one its own log, or at least a prefix
        self.log = storage_plugin_log

        self._dirty_alerts = set()
        self._alerts = {}

    def initial_scan(self):
        """To be implemented by subclasses.  Identify all resources
           present at this time and call register_resource on them.
           
           Any plugin which throws an exception from here is assumed
           to be broken - this will not be retried.  If one of your
           controllers is not contactable, you must handle that and 
           when it comes back up let us know during an update call."""
        raise NotImplementedError

    def update_scan(self):
        """Optionally implemented by subclasses.  Perform any required
           periodic refresh of data and update any resource instances"""
        pass

    # commit_on_success is important here and in update_scan, because
    # if someone is registering a resource with parents
    # and something goes wrong, we must not accidently
    # leave it without parents, as that would cause the
    # it to incorrectly be considered a 'root' resource
    @transaction.commit_on_success
    def do_initial_scan(self):
        self.initial_scan()
        # Now, for every resource in my cache:
        # If its DB record has children which aren't in my cache
        # then remove those child relationships and if the child 
        # now has no parents then remove it.
        # There is a rule implied here: multiple plugin instances
        # are allowed to refer to the same resources with different
        # sets of parents, but if you report a resource you must be able to 
        # report all its children too.
        
        for pk, resource in self._resource_cache.items():
            record = StorageResourceRecord.objects.get(pk = pk)
            
            for c in StorageResourceRecord.objects.filter(parents = record):
                if not c.pk in self._resource_cache:
                    storage_plugin_log.info("Culling resource %s" % c)
                    c.parents.remove(record)
                    if c.parents.count() == 0:
                        self.cull_resource(c)

    def cull_resource(self, resourcerecord):
        """Remove a resource from
        the database and remove any of its children which are
        orphaned as a consequence"""
        # If we have ended up with an orphaned database record which
        # is also in the set of resources reported by the running
        # plugin then something has gone seriously wrong.
        storage_plugin_log.info("cull_resource: %s" % resourcerecord)

        for c in StorageResourceRecord.objects.filter(parents = resourcerecord):
            c.parents.remove(resourcerecord)
            if c.parents.count() == 0:
                self.cull_resource(c)
            else:
                storage_plugin_log.info("resource %s still has %d parents" % (c, c.parents.count()))

        if resourcerecord.pk in self._resource_cache:
            del self._resource_cache[resourcerecord.pk]
        resourcerecord.delete()

    @transaction.commit_on_success
    def do_periodic_update(self):
        self.update_scan()
        for pk, resource in self._resource_cache.items():
            if resource.dirty():
                resource.save()
            for name,ac in resource._alert_conditions.items():
                alert_list = ac.test(resource)
                for name, attribute, active in alert_list:
                    self.notify_alert(active, resource, name, attribute)
        
        for (resource,attribute,alert_class) in self._dirty_alerts:
            active = self._alerts[(resource,attribute,alert_class)]

            from configure.models import StorageResourceRecord
            from configure.models import StorageResourceAlert
            try:
                vrr = StorageResourceRecord.objects.get(pk = resource._handle)
            except StorageResourceRecord.DoesNotExist:
                # Handle a lingering alert from a now-deleted object
                del self._alerts[(resource,attribute,alert_class)]

            StorageResourceAlert.notify(vrr, active, alert_class=alert_class, attribute=attribute)
        # TODO: lock _alerts
        self._dirty_alerts.clear()

    def get_root_resources(self):
        """Return any existing resources for this plugin which
           have no parents.  e.g. depending on the plugin this
           might be chassis, hosts.  Usually something that 
           holds an IP address for this plugin to reach out to.
           Plugins may call this during their initial_scan 
           implementation.

           This information is not simply included in the arguments
           to initial_scan, because some plugins may either use 
           their own autodiscovery mechanism or run locally on 
           a controller and therefore need no hints from us."""
        from configure.lib.storage_plugin import storage_plugin_manager 
        records = StorageResourceRecord.objects.\
               filter(resource_class__storage_plugin__module_name = self.__class__.__module__).\
               filter(parents = None)

        resources = []
        for vrr in records:
            if vrr.pk in self._resource_cache:
                resources.append(self._resource_cache[vrr.pk])
                continue

            resource = vrr.to_resource()
            self._resource_cache[vrr.pk] = resource
            resources.append(resource)

        return resources

    def _lookup_global_resource(self, klass, **attrs):
        """Helper for StoragePlugin subclasses to retrieve resources
           which they have already registered, by global ID.  Implementors
           could equally maintain their own store after initial_scan, this
           is purely to save time in cases where a global ID is available."""

        return self._lookup_local_resource(None, klass, **attrs)

    def _lookup_local_resource(self, scope_resource, klass, **attrs):
        """Note: finds only resources registered in this plugin instance -- if it is
        found in the database but not in _resource_cache then raises an exception"""
        assert(issubclass(klass, StorageResource))

        if scope_resource:
            scope_resource_pk = scope_resource._handle
        else:
            scope_resource_pk = None

        try:
            record = StorageResourceRecord.objects.\
                   filter(resource_class__class_name = klass.__name__).\
                   filter(resource_class__storage_plugin__module_name = self.__class__.__module__).\
                   filter(storage_id_str = klass(**attrs).id_str()).\
                   filter(storage_id_scope = scope_resource_pk).get()
        except StorageResourceRecord.DoesNotExist:
            storage_plugin_log.debug("ResourceNotFound: %s %s %s" % (klass.__name__, self.__class__.__module__, klass(**attrs).id_str()))
            raise ResourceNotFound()

        try:
            return self._resource_cache[record.pk]
        except KeyError:
            raise ResourceNotFound()

    def lookup_children(self, parent, child_klass = None):
        """Helper for StoragePlugin subclasses to retrieve all children
           that they have registered of a resource which they have
           registered, optionally filtered to only children of a particular
           class"""
        child_records = StorageResourceRecord.objects.\
               filter(resource_class__storage_plugin__module_name = self.__class__.__module__).\
               filter(parents = parent._handle)

        if child_klass:
            assert(issubclass(child_klass, StorageResource))
            child_records = child_records.filter(resource_class__class_name = child_klass.__name__)

        child_resources = []
        for c in child_records:
            try:
                child_resources.append(self._resource_cache[c.pk])
            except KeyError:
                # Filtering output to only those in resource_cache, which
                # may not include everything we get from the DB
                pass
        return child_resources

    def _find_ancestor_of_type(self, klass, root):
        """Given a StorageResource 'root', find a resource
           in the ancestor tree (including root) which is 
           of type klass."""
        if isinstance(root, klass):
            return root
        else:
            for p in root._parents:
                try:
                    return self._find_ancestor_of_type(klass, p)
                except ResourceNotFound:
                    pass

        # Fall through: root wasn't of type klass, and none of
        # its ancestors were either
        raise ResourceNotFound()

    def lookup_resource(self, klass, parents = [], **attrs):
        if isinstance(klass.identifier, GlobalId):
            return self._lookup_global_resource(klass, **attrs)
        elif isinstance(klass.identifier, LocalId):
            # Find the scope ancestor
            scope_resource = None
            for p in parents:
                try:
                    scope_resource = self._find_ancestor_of_type(klass.identifier.parent_klass, p)
                except ResourceNotFound:
                    pass
            if not scope_resource:
                raise ResourceNotFound()
                           
            return self._lookup_local_resource(scope_resource, klass, **attrs)

    def update_or_create(self, klass, parents = [], **attrs):
        try:
            existing = self.lookup_resource(klass, parents = parents, **attrs)
            for k,v in attrs.items():
                setattr(existing, k, v)
            for p in parents:
                existing.add_parent(p)
            return existing, False
        except ResourceNotFound:
            resource = klass(**attrs)
            for p in parents:
                resource.add_parent(p)
            self._register_resource(resource)
            return resource, True

    def _register_resource(self, resource):
        """Register a resource:
           * Validate its attributes
           * Create a StorageResourceRecord if it doesn't already
             exist.
           * Update StorageResourceRecord.storage_dict from resource._storage_dict
           * Populate its _handle attribute with a reference
             to a StorageResourceRecord.
             
           You may only call this once per plugin instance on 
           a particular resource."""
        assert(isinstance(resource, StorageResource))
        assert(self._handle)
        assert(not resource._handle)

        resource.validate()

        id_string = resource.id_str()

        if isinstance(resource.identifier, GlobalId):
            id_scope = None
        elif isinstance(resource.identifier, LocalId):
            scope_parent = None
            for p in resource._parents:
                try:
                    scope_parent = self._find_ancestor_of_type(resource.identifier.parent_klass, p)
                except ResourceNotFound:
                    pass

            if not scope_parent:
                raise RuntimeError("Resource %s scoped to resource of type %s, but has no parent of that type!  Its parents are: %s" % (resource, resource.identifier.parent_klass, resource._parents))
            if not scope_parent._handle:
                raise RuntimeError("Resource %s's scope parent %s has not been registered yet (parents must be registered before children)" % (resource, scope_parent))

            id_scope = StorageResourceRecord.objects.get(pk=scope_parent._handle)

        from configure.lib.storage_plugin import storage_plugin_manager
        resource_class_id = storage_plugin_manager.get_plugin_resource_class_id(
                resource.__class__.__module__,
                resource.__class__.__name__
                )
        record, created = StorageResourceRecord.objects.get_or_create(
                resource_class_id = resource_class_id,
                storage_id_str = id_string,
                storage_id_scope = id_scope)

        if self._resource_cache.has_key(record.pk):
            # NB an alternative strategy would be to have register return a ref
            # and just return the cached one in this case.
            raise RuntimeError('Cannot register the same resource twice')

        resource._handle = record.pk

        if not created:
            # In case any attributes which existed last time have now gone away, 
            # remove anything saved which is not present on this new instance.
            from django.db.models import Q
            attrs_set = resource._storage_dict.keys()
            record.storageresourceattribute_set.filter(~Q(key__in = attrs_set)).delete()

        # save will write the StorageResourceAttribute records
        resource.save()

        storage_plugin_log.debug("Looked up StorageResourceRecord %s for %s id=%s (created=%s)" % (record.id, resource.__class__.__name__, id_string, created))

        for parent in resource._parents:
            if not parent._handle:
                raise RuntimeError("Parent resources must be registered before their children")
            parent_record = StorageResourceRecord.objects.get(pk = parent._handle)
            record.parents.add(parent_record)

        self._resource_cache[resource._handle] = resource        

    def notify_alert(self, active, resource, alert_name, attribute = None):
        # This will be flushed through to the database by update_scan
        key = (resource,attribute,alert_name)
        value = active
        try:
            existing = self._alerts[key]
            if existing == (value):
                return
        except KeyError:
            pass

        self._alerts[key] = value
        self._dirty_alerts.add(key)

    def update_statistic(self, resource, stat, value):
        pass

    def deregister_resource(self, resource):
        if not resource._handle:
            raise RuntimeError("Cannot deregister resource which has not been registered")

        record = StorageResourceRecord.objects.get(pk = resource._handle)
        self.cull_resource(record)



