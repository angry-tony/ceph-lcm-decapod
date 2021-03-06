# -*- coding: utf-8 -*-
# Copyright (c) 2016 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Base plugin structure for playbook."""


import abc
import contextlib
import enum
import functools
import os
import shutil
import sys
import traceback

from decapod_common import config
from decapod_common import exceptions
from decapod_common import log
from decapod_common import networkutils
from decapod_common import pathutils
from decapod_common import playbook_plugin_hints
from decapod_common import process
from decapod_common.models import cluster_data
from decapod_common.models import server
from decapod_common.models import task


LOG = log.getLogger(__name__)
"""Logger."""

PATH_CEPH_ANSIBLE = pathutils.ROOT.joinpath("opt", "ceph-ansible")


@enum.unique
class ServerListPolicy(enum.IntEnum):
    any_server = 0
    in_this_cluster = 1
    not_in_this_cluster = 2
    in_other_cluster = 3
    not_in_other_cluster = 4
    in_any_cluster = 5
    not_in_any_cluster = 6

    @staticmethod
    def server_list_as_string(servers):
        return ", ".join(sorted(srv.model_id for srv in servers))

    def check(self, cluster_model, servers):
        cls = self.__class__

        if not servers:
            raise ValueError("Servers should not be empty.")

        if self == cls.any_server:
            return
        elif self == cls.in_this_cluster:
            return cls.check_in_this_cluster(cluster_model, servers)
        elif self == cls.not_in_this_cluster:
            return cls.check_not_in_this_cluster(cluster_model, servers)
        elif self == cls.in_other_cluster:
            return cls.check_in_other_cluster(cluster_model, servers)
        elif self == cls.not_in_other_cluster:
            return cls.check_not_in_other_cluster(cluster_model, servers)
        elif self == cls.in_any_cluster:
            return cls.check_in_any_cluster(cluster_model, servers)

        return cls.check_not_in_any_cluster(cluster_model, servers)

    @classmethod
    def check_in_this_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id != cluster_model.model_id
        ]
        if not negative_cond:
            return

        message = "Servers {0} do not belong to cluster {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_not_in_this_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id == cluster_model.model_id
        ]
        if not negative_cond:
            return

        message = "Servers {0} belong to cluster {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_in_other_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id in (cluster_model.model_id, None)
        ]
        if not negative_cond:
            return

        message = "Servers {0} not in other cluster than {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_not_in_other_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id not in (cluster_model.model_id, None)
        ]
        if not negative_cond:
            return

        message = "Servers {0} in other cluster than {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_in_any_cluster(cls, cluster_model, servers):
        negative_cond = [srv for srv in servers if not srv.cluster_id]
        if not negative_cond:
            return

        message = "Servers {0} are not in any cluster".format(
            cls.server_list_as_string(negative_cond)
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_not_in_any_cluster(cls, cluster_model, servers):
        negative_cond = [srv for srv in servers if srv.cluster_id]
        if not negative_cond:
            return

        message = "Servers {0} are in clusters".format(
            cls.server_list_as_string(negative_cond)
        )
        LOG.warning(message)
        raise ValueError(message)


class Base(metaclass=abc.ABCMeta):

    NAME = None
    PLAYBOOK_FILENAME = None
    CONFIG_FILENAME = None
    DESCRIPTION = ""
    PUBLIC = True
    REQUIRED_SERVER_LIST = True
    SERVER_LIST_POLICY = ServerListPolicy.any_server

    @property
    def env_task_id(self):
        return os.getenv(process.ENV_TASK_ID)

    @property
    def env_entry_point(self):
        return os.getenv(process.ENV_ENTRY_POINT)

    @property
    def task(self):
        if not self.env_task_id:
            return None

        return self.get_task(self.env_task_id)

    def __init__(self, entry_point, module_name):
        self.name = self.NAME or entry_point
        self.playbook_filename = self.PLAYBOOK_FILENAME or "playbook.yaml"
        self.config_filename = self.CONFIG_FILENAME or "config.yaml"

        self.module_name = module_name
        self.entry_point = entry_point
        self.config = self.load_config(self.config_filename)
        self.proc = None

    def get_filename(self, filename):
        return pathutils.resource(self.module_name, filename)

    def load_config(self, cnf):
        return load_config(self.get_filename(cnf or self.config_filename))

    @functools.lru_cache()
    def get_task(self, task_id):
        return task.Task.find_by_id(task_id)

    def get_extra_vars(self, task):
        return {}

    def on_pre_execute(self, task):
        pass

    def on_post_execute(self, task, *exc_info):
        pass

    @abc.abstractmethod
    def compose_command(self, task):
        raise NotImplementedError()

    @abc.abstractmethod
    def get_dynamic_inventory(self):
        raise NotImplementedError()

    @contextlib.contextmanager
    def execute(self, task):
        try:
            LOG.info("Execute pre-run step for %s", self.entry_point)
            try:
                self.on_pre_execute(task)
            finally:
                self.compose_command(task)
                LOG.info("Finish execution of pre-run step for %s",
                         self.entry_point)

            LOG.info("Execute %s for %s",
                     self.proc.commandline, self.entry_point)
            LOG.debug("Commandline: \"%s\"", self.proc.printable_commandline)
            yield self.proc.run()
        finally:
            LOG.info("Execute post-run step for %s", self.entry_point)
            self.on_post_execute(task, *sys.exc_info())
            LOG.info("Finish execution of post-run step for %s",
                     self.entry_point)

        LOG.info("Finish execute %s for %s",
                 self.proc.commandline, self.entry_point)

    def prepare_plugin(self):
        pass


class Ansible(Base, metaclass=abc.ABCMeta):

    MODULE = None
    BECOME = True
    ONE_LINE = True
    HINTS = []

    @abc.abstractmethod
    def compose_command(self, task):
        self.proc = process.Ansible(self.entry_point, task, self.MODULE)

        if self.ONE_LINE:
            self.proc.options["--one-line"] = process.NO_VALUE
        if self.BECOME:
            self.proc.options["--become"] = process.NO_VALUE

        extra = self.get_extra_vars(task)
        if extra:
            self.proc.options["--extra-vars"] = process.jsonify(extra)


class Playbook(Base, metaclass=abc.ABCMeta):

    BECOME = False
    HINTS = None
    CLUSTER_MUST_BE_DEPLOYED = True

    @property
    def playbook_config(self):
        if not self.task:
            return None

        return self.get_playbook_configuration(self.task)

    @functools.lru_cache()
    def get_playbook_configuration(self, task):
        from decapod_common.models import playbook_configuration

        if not task:
            return None

        return playbook_configuration.PlaybookConfigurationModel.find_by_id(
            task.data["playbook_configuration_id"]
        )

    def compose_command(self, task):
        self.proc = process.AnsiblePlaybook(self.entry_point, task)
        self.proc.args.append(str(self.get_filename(self.playbook_filename)))
        self.proc.options["-vvv"] = process.NO_VALUE

        if self.BECOME:
            self.proc.options["--become"] = process.NO_VALUE

        extra = self.get_extra_vars(task)
        if extra:
            self.proc.options["--extra-vars"] = process.jsonify(extra)

    def get_dynamic_inventory(self):
        if self.playbook_config:
            return self.playbook_config.configuration["inventory"]

    def get_extra_vars(self, task):
        config = self.get_playbook_configuration(task)
        config = config.configuration["global_vars"]
        config["decapod_common_playbooks"] = str(pathutils.resource(
            "decapod_common", "playbooks"))

        return config

    def build_playbook_configuration(self, cluster, servers, hints):
        if isinstance(self.HINTS, playbook_plugin_hints.Hints):
            hints = self.HINTS.consume(hints)
        else:
            hints = {}

        if self.CLUSTER_MUST_BE_DEPLOYED and not cluster.configuration.state:
            raise exceptions.ClusterMustBeDeployedError()

        extra, inventory = self.make_playbook_configuration(
            cluster, servers, hints)

        return {
            "global_vars": extra,
            "inventory": inventory
        }

    def on_post_execute(self, task, *exc_info):
        from decapod_common.models import execution

        try:
            if exc_info[0] is None:
                self.write_header()
            else:
                self.write_error(*exc_info)

            execution_model = execution.ExecutionModel.find_by_model_id(
                task.execution_id)
            self.proc.stdout_file.seek(0)
            with execution_model.new_logfile as logfp:
                shutil.copyfileobj(self.proc.stdout_file, logfp)
        except Exception as exc:
            LOG.exception("Cannot save execution log of %s: %s",
                          task.execution_id, exc)
        finally:
            self.proc.stdout_file.close()

        super().on_post_execute(task, *exc_info)

    def write_header(self):
        header = self.proc.printable_commandline
        header_length = min(len(header), 80)
        header_top = " Ansible commandline ".center(header_length, "=")
        header = "\n\n{0}\n{1}\n{2}\n".format(
            header_top, header, "=" * header_length)
        header = header.encode("utf-8")
        self.proc.fileio.write(header)

    def write_error(self, exc_type, exc_value, exc_tb):
        data = traceback.format_exception(exc_type, exc_value, exc_tb)
        data = "".join(data)
        data = "\nInternal error\n\n{0}\n".format(data)
        data = data.encode("utf-8")
        self.proc.fileio.write(data)

    @abc.abstractmethod
    def make_playbook_configuration(self, servers, hints):
        raise NotImplementedError()


class CephAnsiblePlaybook(Playbook, metaclass=abc.ABCMeta):

    CEPH_ANSIBLE_CONFIGFILE = pathutils.resource(
        "decapod_common", "configs", "ceph-ansible-defaults.yaml")

    @classmethod
    def get_ceph_ansible_common_settings(cls, cluster, servers, *,
                                         verify_ceph_version=False):
        config = load_config(cls.CEPH_ANSIBLE_CONFIGFILE)

        result = {
            "ceph_{0}".format(config["install"]["source"]): True,
            "ceph_nfs_access_type": config["nfs"]["ganesha"]["access_type"],
            "ceph_nfs_ceph_access_type": config["nfs"]["ceph"]["access_type"],
            "ceph_nfs_ceph_export_id": config["nfs"]["ceph"]["export_id"],
            "ceph_nfs_ceph_protocols": config["nfs"]["ceph"]["protocols"],
            "ceph_nfs_ceph_pseudo_path": config["nfs"]["ceph"]["pseudo_path"],
            "ceph_nfs_export_id": config["nfs"]["ganesha"]["export_id"],
            "ceph_nfs_log_file": config["nfs"]["ganesha"]["log_file"],
            "ceph_nfs_protocols": config["nfs"]["ganesha"]["protocols"],
            "ceph_nfs_pseudo_path": config["nfs"]["ganesha"]["pseudo_path"],
            "ceph_nfs_rgw_access_type": config["nfs"]["rgw"]["access_type"],
            "ceph_nfs_rgw_export_id": config["nfs"]["rgw"]["export_id"],
            "ceph_nfs_rgw_protocols": config["nfs"]["rgw"]["protocols"],
            "ceph_nfs_rgw_pseudo_path": config["nfs"]["rgw"]["pseudo_path"],
            "ceph_nfs_rgw_user": config["nfs"]["rgw"]["user"],
            "ceph_restapi_port": config["restapi_port"],
            "ceph_stable_distro_source": config["install"]["distro_source"],
            "ceph_stable_release": config["install"]["release"],
            "ceph_stable_repo": config["install"]["repo"],
            "ceph_stable_repo_key": config["install"]["repo_key"],
            "ceph_stable_repo_keyserver": config["install"]["keyserver"],
            "ceph_version_verify_packagename": config["ceph_version_verify_packagename"],  # NOQA
            "ceph_version_verify": verify_ceph_version,
            "cluster": cluster.name,
            "common_single_host_mode": True,  # allow to deploy single OSD
            "copy_admin_key": bool(config.get("copy_admin_key", False)),
            "fsid": cluster.model_id,
            "journal_size": config["journal"]["size"],
            "max_open_files": config["max_open_files"],
            "nfs_file_gw": False,
            "nfs_obj_gw": False,
            "mds_max_mds": config["mds"]["max"],
            "mds_allow_multimds": config["mds"]["multi"],
            "os_tuning_params": [],
            "public_network": str(networkutils.get_public_network(servers)),
            "radosgw_civetweb_num_threads": config["radosgw"]["num_threads"],
            "radosgw_civetweb_port": config["radosgw"]["port"],
            "radosgw_dns_s3website_name": config["radosgw"]["dns_s3website_name"],  # NOQA
            "radosgw_static_website": config["radosgw"]["static_website"],
            "radosgw_usage_log": config["radosgw"]["usage"]["log"],
            "radosgw_usage_log_flush_threshold": config["radosgw"]["usage"]["log_flush_threshold"],  # NOQA
            "radosgw_usage_log_tick_interval": config["radosgw"]["usage"]["log_tick_interval"],  # NOQA
            "radosgw_usage_max_shards": config["radosgw"]["usage"]["max_shards"],  # NOQA
            "radosgw_usage_max_user_shards": config["radosgw"]["usage"]["user_shards"]  # NOQA
        }
        result["ceph_stable_release_uca"] = result["ceph_stable_distro_source"]

        # FIXME(Sergey Arkhipov): For some reason, Ceph cannot converge
        # if I set another network.
        result["cluster_network"] = result["public_network"]

        for family, values in config.get("os", {}).items():
            for param, value in values.items():
                parameter = {
                    "name": ".".join([family, param]),
                    "value": value
                }
                result["os_tuning_params"].append(parameter)

        return result

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetchdir = None

    def on_pre_execute(self, task):
        self.fetchdir = pathutils.tempdir()
        super().on_pre_execute(task)

    def on_post_execute(self, task, exc_value, exc_type, exc_tb):
        pathutils.remove(self.fetchdir)
        super().on_post_execute(task, exc_value, exc_type, exc_tb)

    def get_extra_vars(self, task):
        config = super().get_extra_vars(task)
        config["fetch_directory"] = str(self.fetchdir)

        return config

    def make_global_vars(self, cluster, servers, hints):
        return self.get_ceph_ansible_common_settings(
            cluster, servers,
            verify_ceph_version=bool(hints.get("ceph_version_verify"))
        )

    def get_dynamic_inventory(self):
        if not self.playbook_config:
            raise exceptions.UnknownPlaybookConfiguration()

        return self.playbook_config.configuration["inventory"]


class CephAnsibleNewWithVerification(CephAnsiblePlaybook):

    PUBLIC = True
    REQUIRED_SERVER_LIST = True
    SERVER_LIST_POLICY = ServerListPolicy.not_in_other_cluster

    def on_pre_execute(self, skip_roles, task):
        super().on_pre_execute(task)

        skip_roles = set(skip_roles)
        playbook_config = self.get_playbook_configuration(task)
        config = playbook_config.configuration["inventory"]
        cluster = playbook_config.cluster
        servers = playbook_config.servers
        servers = {srv.ip: srv for srv in servers}

        for name, group_vars in config.items():
            if name not in skip_roles or not group_vars:
                continue
            group_servers = [servers[ip] for ip in group_vars]
            cluster.add_servers(group_servers, name)

        if cluster.configuration.changed:
            cluster.save()

    def make_playbook_configuration(self, cluster, servers, hints):
        data = cluster_data.ClusterData.find_one(cluster.model_id)
        global_vars = self.make_global_vars(cluster, data, servers, hints)
        inventory = self.make_inventory(cluster, data, servers, hints)

        return global_vars, inventory

    def make_global_vars(self, cluster, data, servers, hints):
        result = super().make_global_vars(cluster, servers, hints)
        result.update(data.global_vars)

        result["ceph_version_verify"] = bool(hints["ceph_version_verify"])

        return result

    def get_inventory_groups(self, cluster, servers, hints):
        cluster_servers = server.ServerModel.cluster_servers(cluster.model_id)
        cluster_servers = {item._id: item for item in cluster_servers}

        mons = [
            cluster_servers[item["server_id"]]
            for item in cluster.configuration.state if item["role"] == "mons"]

        return {
            "mons": mons,
            "already_deployed": list(cluster_servers.values())
        }

    def make_inventory(self, cluster, data, servers, hints):
        groups = self.get_inventory_groups(cluster, servers, hints)
        inventory = {"_meta": {"hostvars": {}}}

        for name, group_servers in groups.items():
            for srv in group_servers:
                inventory.setdefault(name, []).append(srv.ip)

                hostvars = inventory["_meta"]["hostvars"].setdefault(
                    srv.ip, {})
                hostvars.update(data.get_host_vars(srv.ip))
                hostvars.setdefault("ansible_user", srv.username)

        return inventory


class CephAnsiblePlaybookRemove(CephAnsiblePlaybook):

    PUBLIC = True
    REQUIRED_SERVER_LIST = True
    SERVER_LIST_POLICY = ServerListPolicy.in_this_cluster

    def on_post_execute(self, groupname, task, exc_value, exc_type, exc_tb):
        super().on_post_execute(task, exc_value, exc_type, exc_tb)

        if exc_value:
            LOG.warning("Cannot remove %s host: %s (%s)",
                        self.entry_point, exc_value, exc_type)
            raise exc_value

        playbook_config = self.get_playbook_configuration(task)
        config = playbook_config.configuration["inventory"]
        cluster = playbook_config.cluster
        servers = playbook_config.servers
        servers = {srv.ip: srv for srv in servers}

        group_vars = config.pop(groupname)
        group_servers = [servers[ip] for ip in group_vars]
        cluster.remove_servers(group_servers, groupname)

        if cluster.configuration.changed:
            cluster.save()

    def make_playbook_configuration(self, cluster, servers, hints):
        data = cluster_data.ClusterData.find_one(cluster.model_id)
        global_vars = self.make_global_vars(cluster, data, servers, hints)
        inventory = self.make_inventory(cluster, data, servers, hints)

        return global_vars, inventory

    def make_global_vars(self, cluster, data, servers, hints):
        return {
            "cluster": data.global_vars.get("cluster", cluster.name)
        }

    def make_inventory(self, cluster, data, servers, hints):
        groups = self.get_inventory_groups(cluster, servers, hints)
        inventory = {"_meta": {"hostvars": {}}}

        for name, group_servers in groups.items():
            for srv in group_servers:
                inventory.setdefault(name, []).append(srv.ip)
                hostvars = inventory["_meta"]["hostvars"].setdefault(
                    srv.ip, {})

                hostvars.update(data.get_host_vars(srv.ip))
                hostvars.setdefault("ansible_user", srv.username)

        return inventory


@functools.lru_cache()
def load_config(filename):
    return config.yaml_load(filename)
