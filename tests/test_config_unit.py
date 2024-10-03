"""Unit testing for the config module."""

import pytest
import pytest_mock

import ansibleinventorycmdb

DEFAULT_CONFIG = ansibleinventorycmdb.config.DEFAULT_CONFIG


def test_config_permissions_error_read(place_test_config, tmp_path, mocker: pytest_mock.plugin.MockerFixture):
    """Mock a Permissions error with mock_open."""
    place_test_config("testing_true_valid.yml", tmp_path)

    mock_open_func = mocker.mock_open(read_data="")
    mock_open_func.side_effect = PermissionError("Permission denied")

    mocker.patch("builtins.open", mock_open_func)

    # TEST: PermissionsError is raised.
    with pytest.raises(PermissionError):
        ansibleinventorycmdb.config.AnsibleInventoryCmdbConfig(instance_path=tmp_path)


def test_config_permissions_error_write(place_test_config, tmp_path, mocker: pytest_mock.plugin.MockerFixture):
    """Mock a Permissions error with mock_open."""
    place_test_config("testing_true_valid.yml", tmp_path)

    conf = ansibleinventorycmdb.config.AnsibleInventoryCmdbConfig(instance_path=tmp_path)

    mock_open_func = mocker.mock_open(read_data="")
    mock_open_func.side_effect = PermissionError("Permission denied")

    mocker.patch("builtins.open", mock_open_func)

    # TEST: PermissionsError is raised.
    with pytest.raises(PermissionError):
        conf._write_config()


def test_dictionary_functions_of_config(place_test_config, tmp_path):
    """Test the functions in the config object that let it behave like a dictionary."""
    place_test_config("testing_true_valid.yml", tmp_path)

    conf = ansibleinventorycmdb.config.AnsibleInventoryCmdbConfig(instance_path=tmp_path)

    # TEST: __contains__ method.
    assert "cmdb" in conf, "__contains__ method of config object doesn't work"

    # TEST: __repr__ method.
    assert isinstance(str(conf), str), "__repr__ method of config object doesn't work"

    # TEST: __getitem__ method.
    assert isinstance(conf["cmdb"], dict), "__getitem__ method of config object doesn't work"

    from collections.abc import ItemsView

    # TEST: .items() method.
    assert isinstance(conf.items(), ItemsView), ".items() method of config object doesn't work"


def test_config_dictionary_merge(place_test_config, tmp_path, get_test_config):
    """Unit test the dictionary merge in _merge_with_defaults."""
    place_test_config("testing_true_valid.yml", tmp_path)

    conf = ansibleinventorycmdb.config.AnsibleInventoryCmdbConfig(instance_path=tmp_path)

    test_dictionaries = [
        {},
        get_test_config("logging_invalid.yml"),
        get_test_config("testing_true_valid.yml"),
    ]

    for test_dictionary in test_dictionaries:
        result_dict = conf._merge_with_defaults(DEFAULT_CONFIG, test_dictionary)

        # TEST: Check that the resulting config after ensuring default is valid
        assert isinstance(result_dict["cmdb"], dict)
        assert isinstance(result_dict["logging"], dict)
        assert isinstance(result_dict["logging"]["path"], str)
        assert isinstance(result_dict["logging"]["level"], str)
        assert isinstance(result_dict["flask"], dict)

    # TEST: If an item isn't in the schema, it still ends up around, not that this is a good idea...
    result_dict = conf._merge_with_defaults(DEFAULT_CONFIG, {"TEST_CONFIG_ENTRY_NOT_IN_SCHEMA": "lmao"})
    assert result_dict["TEST_CONFIG_ENTRY_NOT_IN_SCHEMA"]


def test_config_dictionary_not_in_schema(place_test_config, tmp_path, caplog: pytest.LogCaptureFixture):
    """Unit test _warn_unexpected_keys."""
    place_test_config("testing_true_valid.yml", tmp_path)

    conf = ansibleinventorycmdb.config.AnsibleInventoryCmdbConfig(instance_path=tmp_path)

    test_config = {
        "TEST_CONFIG_ROOT_ENTRY_NOT_IN_SCHEMA": "",
        "cmdb": {"TEST_CONFIG_APP_ENTRY_NOT_IN_SCHEMA": ""},
    }

    # TEST: Warning when config loaded has a key that is not in the schema
    conf._warn_unexpected_keys(DEFAULT_CONFIG, test_config, "<root>")
    assert "Config entry key <root>[TEST_CONFIG_ROOT_ENTRY_NOT_IN_SCHEMA] not in schema" in caplog.text
    assert "Config entry key [cmdb][TEST_CONFIG_APP_ENTRY_NOT_IN_SCHEMA] not in schema" in caplog.text


def test_load_write_no_config_path(place_test_config, tmp_path):
    """Unit test the dictionary merge in _merge_with_defaults."""
    place_test_config("testing_true_valid.yml", tmp_path)

    conf = ansibleinventorycmdb.config.AnsibleInventoryCmdbConfig(instance_path=tmp_path)

    conf._config_path = None

    # TEST: PermissionsError is raised.
    with pytest.raises(ValueError, match="Config path not set, cannot load config"):
        conf._load_file()

    # TEST: PermissionsError is raised.
    with pytest.raises(ValueError, match="Config path not set, cannot write config"):
        conf._write_config()
