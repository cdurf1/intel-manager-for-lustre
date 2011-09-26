

# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

"""This module defines StoragePluginManager which loads and provides
access to StoragePlugins and their StorageResources"""

from configure.lib.storage_plugin.resource import StorageResource, GlobalId, LocalId
from configure.lib.storage_plugin.plugin import StoragePlugin
from configure.lib.storage_plugin.log import storage_plugin_log
from configure.models import *
from django.db import transaction
import json

class LoadedResourceClass(object):
    """Convenience store of introspected information about StorageResource 
       subclasses from loaded modules."""
    def __init__(self, resource_class, resource_class_id):
        self.resource_class = resource_class
        self.resource_class_id = resource_class_id

class LoadedPlugin(object):
    """Convenience store of introspected information about loaded 
       plugin modules."""
    def __init__(self, module, plugin_class):
        # Map of name string to class
        self.resource_classes = {}
        self.module = module
        self.plugin_class = plugin_class
        self.plugin_record, created = StoragePluginRecord.objects.get_or_create(module_name = module.__name__)

        import inspect
        for name, cls in inspect.getmembers(module):
            if inspect.isclass(cls) and issubclass(cls, StorageResource) and cls != StorageResource:
                # FIXME: this limits plugin authors to putting everything in the same
                # module, don't forget to tell them that!  Doesn't mean they can't break
                # code up between files, but names must all be in the module.
                vrc, created = StorageResourceClass.objects.get_or_create(
                        storage_plugin = self.plugin_record,
                        class_name = name)

                self.resource_classes[name] = LoadedResourceClass(cls, vrc.id)

                for name, stat_obj in cls._storage_statistics.items():
                    class_stat, created = StorageResourceClassStatistic.objects.get_or_create(
                            resource_class = vrc,
                            name = name)

class ResourceQuery(object):
    def __init__(self):
        # Map StorageResourceRecord ID to instantiated StorageResource
        self._pk_to_resource = {}
        
        # Record plugins which fail to load
        self._errored_plugins = set()
        
    def _record_to_resource_parents(self, record):
        if record.pk in self._pk_to_resource:
            storage_plugin_log.debug("Got record %s from cache" % record)
            return self._pk_to_resource[record.pk]
        else:
            resource = self._record_to_resource(record)
            if resource:
                resource._parents = [self._record_to_resource_parents(p) for p in record.parents.all()]
            return resource

    def _record_to_resource(self, record):
        """'record' may be a StorageResourceRecord or an ID.  Returns a
        StorageResource, or None if the required plugin is unavailable"""
        
        if not isinstance(record, StorageResourceRecord):
            if record in self._pk_to_resource:
                return self._pk_to_resource[record]
            record = StorageResourceRecord.objects.get(pk=record)
        else:
            if record.pk in self._pk_to_resource:
                return self._pk_to_resource[record.pk]
            
        plugin_module = record.resource_class.storage_plugin.module_name
        if plugin_module in self._errored_plugins:
            return None
            
        # We have to make sure the plugin is loaded before we
        # try to unpickle the StorageResource class
        try:
            storage_plugin_manager.load_plugin(plugin_module)
        except Exception,e:
            storage_plugin_log.error("Cannot load plugin %s for StorageResourceRecord %d: %s" % (plugin_module, record.id, e))
            self._errored_plugins.add(plugin_module)
            return None

        resource = record.to_resource()
        self._pk_to_resource[record.pk] = resource
        return resource

    # These get_ functions are wrapped in transactions to ensure that 
    # e.g. after reading a parent relationship the parent record will really
    # still be there when we SELECT it.
    # XXX this could potentially cause problems if used from a view function
    # which depends on transaction behaviour, as we would commit their transaction
    # halfway through -- maybe use nested_commit_on_success?
    @transaction.commit_on_success()
    def get_resource(self, vrr_id):
        """Return a StorageResource corresponding to a StorageResourceRecord
        identified by vrr_id.  May raise an exception if the plugin for that
        vrr cannot be loaded for any reason.

        Note: resource._parents will not be populated, you will only
        get the attributes."""

        vrr = StorageResourceRecord.objects.get(pk = vrr_id)
        return self._record_to_resource(vrr)

    @transaction.commit_on_success()
    def get_resource_parents(self, vrr_id):
        """Like get_resource by also fills out entire ancestry"""

        vrr = StorageResourceRecord.objects.get(pk = vrr_id)
        return self._record_to_resource_parents(vrr)

    @transaction.commit_on_success()
    def get_all_resources(self):
        """Return list of all resources for all plugins"""
        records = StorageResourceRecord.objects.all()

        resources = []
        resource_parents = {}
        for vrr in records:
            r = self._record_to_resource(vrr)
            if r:
                resources.append(r)
                for p in vrr.parents.all():
                    r._parents.append(self._record_to_resource(p))

        return resources

    def _load_record_and_children(self, record):
        storage_plugin_log.debug("load_record_and_children: %s" % record)
        resource = self._record_to_resource_parents(record)
        if resource:
            children_records = StorageResourceRecord.objects.filter(
                parents = record)
                
            children_resources = []
            for c in children_records:
                child_resource = self._load_record_and_children(c)
                children_resources.append(child_resource)

            resource._children = children_resources
        return resource

    def get_resource_tree(self, root_records):
        """For a given plugin and resource class, find all instances of that class
        and return a tree of resource instances (with additional 'children' attribute)"""
        storage_plugin_log.debug(">> get_resource_tree")
        tree = []
        for record in root_records:
            tree.append(self._load_record_and_children(record))
        storage_plugin_log.debug("<< get_resource_tree")
        
        return tree    

class StoragePluginManager(object):
    def __init__(self):
        self.loaded_plugins = {}
        self.plugin_sessions = {}

    @transaction.commit_on_success
    def create_root_resource(self, plugin_mod, resource_class_name, **kwargs):
        storage_plugin_log.debug("create_root_resource %s %s %s" % (plugin_mod, resource_class_name, kwargs))
        plugin_class = self.load_plugin(plugin_mod)

        # Try to find the resource class in the plugin module
        resource_class = self.get_plugin_resource_class(plugin_mod, resource_class_name)

        # Construct a record
        record = StorageResourceRecord.create_root(resource_class, kwargs)

        # XXX should we let people modify root records?  e.g. change the IP
        # address of a controller rather than deleting it, creating a new 
        # one and letting the pplugin repopulate us with 'new' resources?
        # This will present the challenge of what to do with instances of
        # StorageResource subclasses which are already present in running plugins.

        storage_plugin_log.debug("create_root_resource created %d" % (record.id))

    def register_plugin(self, plugin_instance):
        """Register a particular instance of a StoragePlugin"""
        # FIXME: only supporting one instance of a plugin class at a time
        session_id = plugin_instance.__class__.__name__
        assert(not session_id in self.plugin_sessions)

        self.plugin_sessions[session_id] = plugin_instance
        storage_plugin_log.info("Registered plugin instance %s with id %s" % (plugin_instance, session_id))
        return session_id

    def get_plugin_resource_class(self, plugin_module, resource_class_name):
        """Return a StorageResource subclass"""
        loaded_plugin = self.loaded_plugins[plugin_module]
        return loaded_plugin.resource_classes[resource_class_name].resource_class

    def get_plugin_resource_class_id(self, plugin_module, resource_class_name):
        """Return a StorageResourceClass primary key"""
        loaded_plugin = self.loaded_plugins[plugin_module]
        return loaded_plugin.resource_classes[resource_class_name].resource_class_id


    def load_plugin(self, module):
        """Load a StoragePlugin class from a module given a
           python path like 'configure.lib.lvm',
           or simply return it if it was already loaded.  Note that the 
           StoragePlugin within the module will not be instantiated when this
           returns, caller is responsible for instantiating it.

           @return A subclass of StoragePlugin"""
        if module in self.loaded_plugins:
            return self.loaded_plugins[module].plugin_class

        # Load the module
        mod = __import__(module)
        components = module.split('.')
        for comp in components[1:]:
            mod = getattr(mod, comp)
        plugin = mod

        # Find all StoragePlugin subclasses in the module
        plugin_klasses = []
        import inspect
        for name, cls in inspect.getmembers(plugin):
            if inspect.isclass(cls) and issubclass(cls, StoragePlugin) and cls != StoragePlugin:
                plugin_klasses.append(cls)
                
        # Make sure we have exactly one StoragePlugin subclass
        if len(plugin_klasses) > 1:
            raise RuntimeError("Module %s defines more than one StoragePlugin: %s!" % (module, plugin_klasses))
        elif len(plugin_klasses) == 0:
            raise RuntimeError("Module %s does not define a StoragePlugin!" % module)
        else:
            plugin_klass = plugin_klasses[0]

        self.loaded_plugins[plugin_klass.__module__] = LoadedPlugin(plugin, plugin_klass)
        return plugin_klass

storage_plugin_manager = StoragePluginManager()



