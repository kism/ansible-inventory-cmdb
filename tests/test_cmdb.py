from ansibleinventorycmdb.cmdb import AnsibleCMDB


def test_object_creation(tmp_path, get_test_config):
    test_config = get_test_config("inventory_defined_valid.yml")

    inventory_dict = test_config["cmdb"]

    cmdb = AnsibleCMDB(instance_path=tmp_path, inventory_dict=inventory_dict)

    assert cmdb is not None

    cmdb.refresh()

    import time

    while cmdb.refresh_required:
        time.sleep(1)

    cmdb._load_url_cache()

    cmdb.get_inventory("test_main")
