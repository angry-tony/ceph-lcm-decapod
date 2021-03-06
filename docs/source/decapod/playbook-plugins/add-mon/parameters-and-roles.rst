.. _plugin_add_monitor_host_parameters_and_roles:

====================
Parameters and roles
====================

The *Add monitor host* plugin parameters are mostly the same as the ones for
the
:ref:`Deploy Ceph cluster <plugin_deploy_ceph_cluster_parameters_and_roles>`
plugin. However, the plugin has the following role:

``mons``
 Defines the nodes to deploy monitors.

.. note::

   For consistency, Decapod checks the Ceph version it is going to deploy. If
   a Ceph cluster has inconsistent versions, the deployment stops and you
   must fix the versions withing the cluster. If the Ceph version you are
   going to deploy is newer that the deployed ones, the process will also stop
   and you must update the cluster packages first.

   The following parameters are responsble for such checks:

   ``ceph_version_verify``
    A boolean setting that checks that strict mode is enabled. If set to
    ``false``, no verification described above is performed.

   ``ceph_version_verify_packagename``
    The name of the package to check. It is not required to configure this
    setting.
