
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

from configure.lib.storage_plugin.resource import StorageResource
from configure.lib.storage_plugin import attributes

class Host(StorageResource):
    human_name = 'Host'
    icon = 'host'

class PhysicalDisk(StorageResource):
    human_name = 'Physical disk'
    icon = 'physical_disk'

class VirtualDisk(StorageResource):
    human_name = 'Virtual disk'
    icon = 'virtual_disk'

class StoragePool(StorageResource):
    human_name = 'Storage pool'
    icon = 'storage_pool'

class Controller(StorageResource):
    pass

class Fan(StorageResource):
    pass

class Enclosure(StorageResource):
    pass

class DeviceNode(StorageResource):
    host = attributes.HostName()
    path = attributes.PosixPath()

    human_name = 'Device node'

