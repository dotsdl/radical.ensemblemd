.. _library:

*****************************
Building Blocks API Reference
*****************************

Execution Context API
=====================

.. autoclass:: radical.ensemblemd.SingleClusterEnvironment
    :members:
    :inherited-members:

.. .. autoclass:: radical.ensemblemd.MultiClusterEnvironment
..     :members:
..     :inherited-members:


.. _kern_api:

Application Kernel API
======================

.. autoclass:: radical.ensemblemd.Kernel
    :members:
    :inherited-members:

Exceptions & Errors
===================

.. automodule:: radical.ensemblemd.exceptions
   :show-inheritance:
   :members: EnsemblemdError, NotImplementedError, TypeError, ArgumentError, FileError, NoKernelPluginError, NoKernelConfigurationError, NoExecutionPluginError
