"""Blueprint one's object..."""

import json
import threading
import time
from http import HTTPStatus

import yaml
from flask import Blueprint, Response, current_app, render_template

from ansibleinventorycmdb.cmdb import AnsibleCMDB

from .logger import get_logger

logger = get_logger(__name__)

# Register this module (__name__) as available to the blueprints of ansibleinventorycmdb, I think https://flask.palletsprojects.com/en/3.0.x/blueprints/
bp = Blueprint("ansibleinventorycmdb", __name__)

cmdb: AnsibleCMDB | None = None

version = None


def str_presenter(dumper: yaml.representer.SafeRepresenter, data: str) -> yaml.nodes.ScalarNode:
    """YAML string presenter, use |- block."""
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # Use with safe


def start_cmdb_bp() -> None:
    """Method to 'configure' this module. Needs to be called under `with app.app_context():` from __init__.py."""
    global cmdb  # noqa: PLW0603 Necessary evil as far as I can tell, could move to all objects but eh...

    cmdb = AnsibleCMDB(current_app.config["cmdb"], current_app.instance_path)  # Create an instance of our CMDB class

    thread = threading.Thread(target=refresh_cmdb)
    thread.daemon = True
    thread.start()


def refresh_cmdb() -> None:
    """Refresh the CMDB data."""
    while True:
        if not isinstance(cmdb, AnsibleCMDB):
            logger.error("No CMDB found, please check the logs.")
            time.sleep(60)
        else:
            if not cmdb.ready:
                logger.info("CMDB not ready, building...")
                cmdb.build()

            if cmdb.refresh_required:
                logger.info("CMDB refresh required, refreshing...")
                cmdb.refresh()

            while True:
                logger.debug("Sleeping before refresh")
                time.sleep(21600)
                cmdb.refresh()
                logger.info("Sleeping for 6 hours")


@bp.route("/")
def home() -> tuple[str, int]:
    """Home webpage."""
    if not isinstance(cmdb, AnsibleCMDB):
        return "No CMDB found, please check the logs.", HTTPStatus.INTERNAL_SERVER_ERROR

    inventories = cmdb.get_inventories()

    return render_template("home.html.j2", inventories=inventories), HTTPStatus.OK


# Flask homepage, generally don't have this as a blueprint.
@bp.route("/inventory/<string:inventory>")
def inventory(inventory: str) -> tuple[str, int]:
    """Flask home."""
    if not isinstance(cmdb, AnsibleCMDB):
        return "No CMDB found, please check the logs.", HTTPStatus.INTERNAL_SERVER_ERROR

    if not cmdb.ready:
        inventory_dict: dict = {"hosts": {}, "groups": {}}
        schema_mapping = {"": "CMDB NOT LOADED, please wait a moment and refresh"}
    else:
        inventory_dict = cmdb.get_inventory(inventory)
        if inventory_dict == {}:
            return render_template("error.html.j2", error=f"Inventory '{inventory}' not found"), HTTPStatus.NOT_FOUND
        try:
            schema_mapping = dict(current_app.config["cmdb"][inventory]["schema_mapping"])
        except KeyError:
            return render_template(
                "error.html.j2", error=f"Inventory '{inventory}' found, but inventory schema not found"
            ), HTTPStatus.NOT_FOUND

    return render_template(
        "inventory.html.j2",
        inventory_name=inventory,
        inventory_dict=inventory_dict,
        schema_mapping=schema_mapping,
    ), HTTPStatus.OK


@bp.route("/inventory/<string:inventory>/host/<string:host>")
def host(inventory: str, host: str) -> tuple[str, int]:
    """Return a JSON response for a host."""
    if not isinstance(cmdb, AnsibleCMDB):
        return "No CMDB found, please check the logs.", HTTPStatus.INTERNAL_SERVER_ERROR

    if not cmdb.ready:
        host_nice_vars = "CMDB not ready, please wait a moment and refresh."
    else:
        # Get copy of cmdb host vars in alphabetical order
        try:
            cmdb_host_vars = cmdb.get_host(inventory, host)["vars"]
        except KeyError:
            return render_template("error.html.j2", error=f"Host '{host}' not found"), 404

        alphabetical_var_dict = dict(sorted(cmdb_host_vars.items(), key=lambda item: str(item[0])))

        host_nice_vars = yaml.dump(alphabetical_var_dict, explicit_start=True, default_flow_style=False, width=1000)

        if host_nice_vars.strip() == "--- {}":
            host_nice_vars = "---"

    return render_template(
        "vars.html.j2", __inventory=inventory, __thing="host_vars", __host=host, __vars=host_nice_vars
    ), HTTPStatus.OK


@bp.route("/inventory/<string:inventory>/group/<string:group>")
def group(inventory: str, group: str) -> tuple[str, int]:
    """Return a JSON response for a group."""
    if not isinstance(cmdb, AnsibleCMDB):
        return "No CMDB found, please check the logs.", HTTPStatus.INTERNAL_SERVER_ERROR

    if not cmdb.ready:
        group_nice_vars = "CMDB not ready, please wait a moment and refresh."
        return render_template(
            "vars.html.j2", __inventory=inventory, __thing="group_vars", __host=group, __vars=group_nice_vars
        ), HTTPStatus.TOO_EARLY

    cmdb_group_vars = cmdb.get_group(inventory, group)

    alphabetical_var_dict = dict(sorted(cmdb_group_vars.items(), key=lambda item: str(item[0])))

    group_nice_vars = yaml.dump(alphabetical_var_dict, explicit_start=True, default_flow_style=False, width=1000)

    if group_nice_vars.strip() == "--- {}":
        group_nice_vars = "---"

    return render_template(
        "vars.html.j2", __inventory=inventory, __thing="group_vars", __host=group, __vars=group_nice_vars
    ), HTTPStatus.OK  # Return a webpage


@bp.route("/health")
def health() -> tuple[Response, int]:
    """Health check endpoint."""
    global version  # noqa: PLW0603

    health = {}

    if not version:
        from ansibleinventorycmdb import __version__

        version = __version__

    health["version"] = version
    return Response(json.dumps(health), status=200, mimetype="application/json"), HTTPStatus.OK
