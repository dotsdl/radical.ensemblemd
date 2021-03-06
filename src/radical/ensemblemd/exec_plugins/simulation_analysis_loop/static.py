#!/usr/bin/env python

"""A static execution plugin for the 'simulation-analysis' pattern.
"""

__author__    = "Ole Weider <ole.weidner@rutgers.edu>"
__copyright__ = "Copyright 2014, http://radical.rutgers.edu"
__license__   = "MIT"

import os
import sys
import traceback
import time
import saga
import datetime
import radical.pilot
from radical.ensemblemd.exceptions import NotImplementedError, EnsemblemdError
from radical.ensemblemd.exec_plugins.plugin_base import PluginBase


# ------------------------------------------------------------------------------
#
_PLUGIN_INFO = {
    "name":         "simulation_analysis_loop.static.default",
    "pattern":      "SimulationAnalysisLoop",
    "context_type": "Static"
}

_PLUGIN_OPTIONS = []

# ------------------------------------------------------------------------------
#
def resolve_placeholder_vars(working_dirs, instance, iteration, sim_width, ana_width, type, path):

    # If replacement not require, return the path as is
    if '$' not in path:
        return path

    # Extract placeholder from path
    if len(path.split('>'))==1:
        placeholder = path.split('/')[0]
    else:
        if path.split('>')[0].strip().startswith('$'):
            placeholder = path.split('>')[0].strip().split('/')[0]
        else:
            placeholder = path.split('>')[1].strip().split('/')[0]

    # $PRE_LOOP
    if placeholder == "$PRE_LOOP":
        return path.replace(placeholder, working_dirs["pre_loop"])

    # $POST_LOOP
    elif placeholder == "$POST_LOOP":
        return path.replace(placeholder, working_dirs["post_loop"])

    # $PREV_SIMULATION
    elif placeholder == "$PREV_SIMULATION":
        if sim_width == ana_width:
            if type == "analysis":
                return path.replace(placeholder, working_dirs['iteration_{0}'.format(iteration)]['simulation_{0}'.format(instance)])
            else:
                raise Exception("$PREV_SIMULATION can only be referenced within analysis step. ")
        else:
            raise Exception("Simulation and analysis 'width' need to be identical for $PREV_SIMULATION to work.")

    # $PREV_ANALYSIS
    elif placeholder == "$PREV_ANALYSIS":
        if sim_width == ana_width:
            if type == "simulation":
                return path.replace(placeholder, working_dirs['iteration_{0}'.format(iteration-1)]['analysis_{0}'.format(instance)])
            else:
                raise Exception("$PREV_ANALYSIS can only be referenced within simulation step. ")
        else:
            raise Exception("Simulation and analysis 'width' need to be identical for $PREV_SIMULATION to work.")

    # $PREV_SIMULATION_INSTANCE_Y
    elif placeholder.startswith("$PREV_SIMULATION_INSTANCE_"):
        y = placeholder.split("$PREV_SIMULATION_INSTANCE_")[1]
        if type == "analysis" and iteration >= 1:
            return path.replace(placeholder, working_dirs['iteration_{0}'.format(iteration)]['simulation_{0}'.format(y)])
        else:
            raise Exception("$PREV_SIMULATION_INSTANCE_Y used in invalid context.")

    # $PREV_ANALYSIS_INSTANCE_Y
    elif placeholder.startswith("$PREV_ANALYSIS_INSTANCE_"):
        y = placeholder.split("$PREV_ANALYSIS_INSTANCE_")[1]
        if type == "simulation" and iteration > 1:
            return path.replace(placeholder, working_dirs['iteration_{0}'.format(iteration-1)]['analysis_{0}'.format(y)])
        else:
            raise Exception("$PREV_ANALYSIS_INSTANCE_Y used in invalid context.")

    # $SIMULATION_ITERATION_X_INSTANCE_Y
    elif placeholder.startswith("$SIMULATION_ITERATION_"):
        x = placeholder.split("_")[2]
        y = placeholder.split("_")[4]
        if type == "analysis" and iteration >= 1:
            return path.replace(placeholder, working_dirs['iteration_{0}'.format(x)]['simulation_{0}'.format(y)])
        else:
            raise Exception("$SIMULATION_ITERATION_X_INSTANCE_Y used in invalid context.")

    # $ANALYSIS_ITERATION_X_INSTANCE_Y
    elif placeholder.startswith("$ANALYSIS_ITERATION_"):
        x = placeholder.split("_")[2]
        y = placeholder.split("_")[4]
        if (type == 'simulation' or type == "analysis") and iteration >= 1:
            return path.replace(placeholder, working_dirs['iteration_{0}'.format(x)]['analysis_{0}'.format(y)])
        else:
            raise Exception("$ANALYSIS_ITERATION_X_INSTANCE_Y used in invalid context.")

    # Nothing to replace here...
    else:
        return path

# ------------------------------------------------------------------------------
#
class Plugin(PluginBase):

    # --------------------------------------------------------------------------
    #
    def __init__(self):
        super(Plugin, self).__init__(_PLUGIN_INFO, _PLUGIN_OPTIONS)

    # --------------------------------------------------------------------------
    #
    def verify_pattern(self, pattern, resource):
        pass

    # --------------------------------------------------------------------------
    #
    def execute_pattern(self, pattern, resource):

        pattern_start_time = datetime.datetime.now()

        #-----------------------------------------------------------------------
        #
        def unit_state_cb (unit, state) :

            if state == radical.pilot.FAILED:
                self.get_logger().error("ComputeUnit error: STDERR: {0}, STDOUT: {0}".format(unit.stderr, unit.stdout))
                self.get_logger().error("Pattern execution FAILED.")
                sys.exit(1)


        self._reporter.ok('>>ok')
        self.get_logger().info("Executing simulation-analysis loop with {0} iterations on {1} allocated core(s) on '{2}'".format(pattern.iterations, resource._cores, resource._resource_key))

        self._reporter.header("Executing simulation-analysis loop with {0} iterations on {1} allocated core(s) on '{2}'".format(pattern.iterations, resource._cores, resource._resource_key))

        working_dirs = {}
        all_cus = []

        #print resource._pilot.description['cores']

        self.get_logger().info("Waiting for pilot on {0} to go Active".format(resource._resource_key))
        self._reporter.info("Job waiting on queue...".format(resource._resource_key))
        resource._pmgr.wait_pilots(resource._pilot.uid,'Active')
        self._reporter.ok("\nJob is now running !".format(resource._resource_key))

        profiling = int(os.environ.get('RADICAL_ENMD_PROFILING',0))

        if profiling == 1:
            from collections import OrderedDict as od
            pattern._execution_profile = []
            enmd_overhead_dict = od()
            cu_dict = od()

        try:

            start_now = datetime.datetime.now()

            resource._umgr.register_callback(unit_state_cb)

            ########################################################################
            # execute pre_loop
            #
            try:

                ################################################################
                # EXECUTE PRE-LOOP

                if profiling == 1:
                    probe_preloop_start = datetime.datetime.now()
                    enmd_overhead_dict['preloop'] = od()
                    enmd_overhead_dict['preloop']['start_time'] = probe_preloop_start
                
                pre_loop = pattern.pre_loop()
                pre_loop._bind_to_resource(resource._resource_key)

                cu = radical.pilot.ComputeUnitDescription()
                cu.name = "pre_loop"

                cu.pre_exec       = pre_loop._cu_def_pre_exec
                cu.executable     = pre_loop._cu_def_executable
                cu.arguments      = pre_loop.arguments
                cu.mpi            = pre_loop.uses_mpi
                cu.input_staging  = pre_loop._cu_def_input_data
                cu.output_staging = pre_loop._cu_def_output_data

                self.get_logger().debug("Created pre_loop CU: {0}.".format(cu.as_dict()))

                self.get_logger().info("Submitted ComputeUnit(s) for pre_loop step.")
                self._reporter.info("\nWaiting for pre_loop step to complete.")
                if profiling == 1:
                    probe_preloop_wait = datetime.datetime.now()
                    enmd_overhead_dict['preloop']['wait_time'] = probe_preloop_wait

                unit = resource._umgr.submit_units(cu)
                all_cus.append(unit)
                resource._umgr.wait_units(unit.uid)

                if profiling == 1:
                    probe_preloop_res = datetime.datetime.now()
                    enmd_overhead_dict['preloop']['res_time'] = probe_preloop_res

                self.get_logger().info("Pre_loop completed.")

                if unit.state != radical.pilot.DONE:
                    raise EnsemblemdError("Pre-loop CU failed with error: {0}".format(unit.stdout))
                working_dirs["pre_loop"] = saga.Url(unit.working_directory).path

                # Process CU information and append it to the dictionary
                if profiling == 1:
                    probe_preloop_done = datetime.datetime.now()
                    enmd_overhead_dict['preloop']['stop_time'] = probe_preloop_done
                    cu_dict['pre_loop'] = unit


                self._reporter.ok('>> done')
                 
            except Exception:
                # Doesn't exist. That's fine as it is not mandatory.
                self.get_logger().info("pre_loop() not defined. Skipping.")
                self._reporter.info("\npre_loop() not defined. Skipping.")
                pass

            ########################################################################
            # execute simulation analysis loop
            #
            for iteration in range(1, pattern.iterations+1):

                working_dirs['iteration_{0}'.format(iteration)] = {}

                ################################################################
                # EXECUTE SIMULATION STEPS

                if profiling == 1:
                    enmd_overhead_dict['iter_{0}'.format(iteration)] = od()
                    cu_dict['iter_{0}'.format(iteration)] = od()

                if isinstance(pattern.simulation_step(iteration=iteration, instance=1),list):
                    num_sim_kerns = len(pattern.simulation_step(iteration=iteration, instance=1))
                else:
                    num_sim_kerns = 1
                #print num_sim_kerns

                all_sim_cus = []
                if profiling == 1:
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']= od()
                    cu_dict['iter_{0}'.format(iteration)]['sim']= list()

                for kern_step in range(0,num_sim_kerns):

                    if profiling == 1:
                        probe_sim_start = datetime.datetime.now()

                        enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['kernel_{0}'.format(kern_step)]= od()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['kernel_{0}'.format(kern_step)]['start_time'] = probe_sim_start

                    s_units = []
                    for s_instance in range(1, pattern._simulation_instances+1):

                        if isinstance(pattern.simulation_step(iteration=iteration, instance=s_instance),list):
                            sim_step = pattern.simulation_step(iteration=iteration, instance=s_instance)[kern_step]
                        else:
                            sim_step = pattern.simulation_step(iteration=iteration, instance=s_instance)

                        sim_step._bind_to_resource(resource._resource_key)

                        # Resolve all placeholders
                        #if sim_step.link_input_data is not None:
                        #    for i in range(len(sim_step.link_input_data)):
                        #        sim_step.link_input_data[i] = resolve_placeholder_vars(working_dirs, s_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "simulation", sim_step.link_input_data[i])


                        cud = radical.pilot.ComputeUnitDescription()
                        cud.name = "sim ;{iteration} ;{instance}".format(iteration=iteration, instance=s_instance)

                        cud.pre_exec       = sim_step._cu_def_pre_exec
                        cud.executable     = sim_step._cu_def_executable
                        cud.arguments      = sim_step.arguments
                        cud.mpi            = sim_step.uses_mpi
                        cud.input_staging  = None
                        cud.output_staging = None

                        # INPUT DATA:
                        #------------------------------------------------------------------------------------------------------------------
                        # upload_input_data
                        data_in = []
                        if sim_step._kernel._upload_input_data is not None:
                            if isinstance(sim_step._kernel._upload_input_data,list):
                                pass
                            else:
                                sim_step._kernel._upload_input_data = [sim_step._kernel._upload_input_data]
                            for i in range(0,len(sim_step._kernel._upload_input_data)):
                                var=resolve_placeholder_vars(working_dirs, s_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "simulation", sim_step._kernel._upload_input_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip()
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip())
                                        }
                                data_in.append(temp)

                        if cud.input_staging is None:
                            cud.input_staging = data_in
                        else:
                            cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # link_input_data
                        data_in = []
                        if sim_step._kernel._link_input_data is not None:
                            if isinstance(sim_step._kernel._link_input_data,list):
                                pass
                            else:
                                sim_step._kernel._link_input_data = [sim_step._kernel._link_input_data]
                            for i in range(0,len(sim_step._kernel._link_input_data)):
                                var=resolve_placeholder_vars(working_dirs, s_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "simulation", sim_step._kernel._link_input_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip(),
                                            'action': radical.pilot.LINK
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip()),
                                            'action': radical.pilot.LINK
                                        }
                                data_in.append(temp)

                        if cud.input_staging is None:
                            cud.input_staging = data_in
                        else:
                            cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # copy_input_data
                        data_in = []
                        if sim_step._kernel._copy_input_data is not None:
                            if isinstance(sim_step._kernel._copy_input_data,list):
                                pass
                            else:
                                sim_step._kernel._copy_input_data = [sim_step._kernel._copy_input_data]
                            for i in range(0,len(sim_step._kernel._copy_input_data)):
                                var=resolve_placeholder_vars(working_dirs, s_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "simulation", sim_step._kernel._copy_input_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip(),
                                            'action': radical.pilot.COPY
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip()),
                                            'action': radical.pilot.COPY
                                        }
                                data_in.append(temp)

                        if cud.input_staging is None:
                            cud.input_staging = data_in
                        else:
                            cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # download input data
                        if sim_step.download_input_data is not None:
                            data_in  = sim_step.download_input_data
                            if cud.input_staging is None:
                                cud.input_staging = data_in
                            else:
                                cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        # OUTPUT DATA:
                        #------------------------------------------------------------------------------------------------------------------
                        # copy_output_data
                        data_out = []
                        if sim_step._kernel._copy_output_data is not None:
                            if isinstance(sim_step._kernel._copy_output_data,list):
                                pass
                            else:
                                sim_step._kernel._copy_output_data = [sim_step._kernel._copy_output_data]
                            for i in range(0,len(sim_step._kernel._copy_output_data)):
                                var=resolve_placeholder_vars(working_dirs, s_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "simulation", sim_step._kernel._copy_output_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip(),
                                            'action': radical.pilot.COPY
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip()),
                                            'action': radical.pilot.COPY
                                        }
                                data_out.append(temp)

                        if cud.output_staging is None:
                            cud.output_staging = data_out
                        else:
                            cud.output_staging += data_out
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # download_output_data
                        data_out = []
                        if sim_step._kernel._download_output_data is not None:
                            if isinstance(sim_step._kernel._download_output_data,list):
                                pass
                            else:
                                sim_step._kernel._download_output_data = [sim_step._kernel._download_output_data]
                            for i in range(0,len(sim_step._kernel._download_output_data)):
                                var=resolve_placeholder_vars(working_dirs, s_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "simulation", sim_step._kernel._download_output_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip()
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip())
                                        }
                                data_out.append(temp)

                        if cud.output_staging is None:
                            cud.output_staging = data_out
                        else:
                            cud.output_staging += data_out
                        #------------------------------------------------------------------------------------------------------------------


                        if sim_step.cores is not None:
                            cud.cores = sim_step.cores

                        s_units.append(cud)

                        if sim_step.get_instance_type == 'single':
                            break
                        
                    self.get_logger().debug("Created simulation CU: {0}.".format(cud.as_dict()))
                    

                    self.get_logger().info("Submitted tasks for simulation iteration {0}.".format(iteration))
                    self.get_logger().info("Waiting for simulations in iteration {0}/ kernel {1}: {2} to complete.".format(iteration,kern_step+1,sim_step.name))


                    self._reporter.info("\nIteration {0}: Waiting for simulation tasks: {1} to complete".format(iteration,sim_step.name))
                    if profiling == 1:
                        probe_sim_wait = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['kernel_{0}'.format(kern_step)]['wait_time'] = probe_sim_wait

                    s_cus = resource._umgr.submit_units(s_units)
                    all_cus.extend(s_cus)
                    all_sim_cus.extend(s_cus)

                    uids = [cu.uid for cu in s_cus]
                    resource._umgr.wait_units(uids)

                    if profiling == 1:
                        probe_sim_res = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['kernel_{0}'.format(kern_step)]['res_time'] = probe_sim_res


                    self.get_logger().info("Simulations in iteration {0}/ kernel {1}: {2} completed.".format(iteration,kern_step+1,sim_step.name))

                    failed_units = ""
                    for unit in s_cus:
                        if unit.state != radical.pilot.DONE:
                            failed_units += " * Simulation task {0} failed with an error: {1}\n".format(unit.uid, unit.stderr)

                    if profiling == 1:
                        probe_sim_done = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['kernel_{0}'.format(kern_step)]['stop_time'] = probe_sim_done

                    self._reporter.ok('>> done')

                if profiling == 1:
                    probe_post_sim_start = datetime.datetime.now()
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['post'] = od()
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['post']['start_time'] = probe_post_sim_start

                # TODO: ensure working_dir <-> instance mapping
                i = 0
                for cu in s_cus:
                    i += 1
                    working_dirs['iteration_{0}'.format(iteration)]['simulation_{0}'.format(i)] = saga.Url(cu.working_directory).path
                
                if profiling == 1:
                    probe_post_sim_end = datetime.datetime.now()
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['sim']['post']['stop_time'] = probe_post_sim_end
                    cu_dict['iter_{0}'.format(iteration)]['sim'] = all_sim_cus

                ################################################################
                # EXECUTE ANALYSIS STEPS

                if isinstance(pattern.analysis_step(iteration=iteration, instance=1),list):
                    num_ana_kerns = len(pattern.analysis_step(iteration=iteration, instance=1))
                else:
                    num_ana_kerns = 1
                #print num_ana_kerns

                all_ana_cus = []
                if profiling == 1:
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['ana'] = od()
                    cu_dict['iter_{0}'.format(iteration)]['ana']= list()

                for kern_step in range(0,num_ana_kerns):

                    if profiling == 1:
                        probe_ana_start = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['kernel_{0}'.format(kern_step)]= od()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['kernel_{0}'.format(kern_step)]['start_time'] = probe_ana_start

                    a_units = []
                    for a_instance in range(1, pattern._analysis_instances+1):

                        if isinstance(pattern.analysis_step(iteration=iteration, instance=a_instance),list):
                            ana_step = pattern.analysis_step(iteration=iteration, instance=a_instance)[kern_step]
                        else:
                            ana_step = pattern.analysis_step(iteration=iteration, instance=a_instance)

                        ana_step._bind_to_resource(resource._resource_key)

                        # Resolve all placeholders
                        #if ana_step.link_input_data is not None:
                        #    for i in range(len(ana_step.link_input_data)):
                        #        ana_step.link_input_data[i] = resolve_placeholder_vars(working_dirs, a_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "analysis", ana_step.link_input_data[i])

                        cud = radical.pilot.ComputeUnitDescription()
                        cud.name = "ana ; {iteration}; {instance}".format(iteration=iteration, instance=a_instance)

                        cud.pre_exec       = ana_step._cu_def_pre_exec
                        cud.executable     = ana_step._cu_def_executable
                        cud.arguments      = ana_step.arguments
                        cud.mpi            = ana_step.uses_mpi
                        cud.input_staging  = None
                        cud.output_staging = None

                        #------------------------------------------------------------------------------------------------------------------
                        # upload_input_data
                        data_in = []
                        if ana_step._kernel._upload_input_data is not None:
                            if isinstance(ana_step._kernel._upload_input_data,list):
                                pass
                            else:
                                ana_step._kernel._upload_input_data = [ana_step._kernel._upload_input_data]
                            for i in range(0,len(ana_step._kernel._upload_input_data)):
                                var=resolve_placeholder_vars(working_dirs, a_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "analysis", ana_step._kernel._upload_input_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip()
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip())
                                        }
                                data_in.append(temp)

                        if cud.input_staging is None:
                            cud.input_staging = data_in
                        else:
                            cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # link_input_data
                        data_in = []
                        if ana_step._kernel._link_input_data is not None:
                            if isinstance(ana_step._kernel._link_input_data,list):
                                pass
                            else:
                                ana_step._kernel._link_input_data = [ana_step._kernel._link_input_data]
                            for i in range(0,len(ana_step._kernel._link_input_data)):
                                var=resolve_placeholder_vars(working_dirs, a_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "analysis", ana_step._kernel._link_input_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip(),
                                            'action': radical.pilot.LINK
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip()),
                                            'action': radical.pilot.LINK
                                        }
                                data_in.append(temp)

                        if cud.input_staging is None:
                            cud.input_staging = data_in
                        else:
                            cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # copy_input_data
                        data_in = []
                        if ana_step._kernel._copy_input_data is not None:
                            if isinstance(ana_step._kernel._copy_input_data,list):
                                pass
                            else:
                                ana_step._kernel._copy_input_data = [ana_step._kernel._copy_input_data]
                            for i in range(0,len(ana_step._kernel._copy_input_data)):
                                var=resolve_placeholder_vars(working_dirs, a_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "analysis", ana_step._kernel._copy_input_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip(),
                                            'action': radical.pilot.COPY
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip()),
                                            'action': radical.pilot.COPY
                                        }
                                data_in.append(temp)

                        if cud.input_staging is None:
                            cud.input_staging = data_in
                        else:
                            cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # download input data
                        if ana_step.download_input_data is not None:
                            data_in  = ana_step.download_input_data
                            if cud.input_staging is None:
                                cud.input_staging = data_in
                            else:
                                cud.input_staging += data_in
                        #------------------------------------------------------------------------------------------------------------------


                        #------------------------------------------------------------------------------------------------------------------
                        # copy_output_data
                        data_out = []
                        if ana_step._kernel._copy_output_data is not None:
                            if isinstance(ana_step._kernel._copy_output_data,list):
                                pass
                            else:
                                ana_step._kernel._copy_output_data = [ana_step._kernel._copy_output_data]
                            for i in range(0,len(ana_step._kernel._copy_output_data)):
                                var=resolve_placeholder_vars(working_dirs, a_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "analysis", ana_step._kernel._copy_output_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip(),
                                            'action': radical.pilot.COPY
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip()),
                                            'action': radical.pilot.COPY
                                        }
                                data_out.append(temp)

                        if cud.output_staging is None:
                            cud.output_staging = data_out
                        else:
                            cud.output_staging += data_out
                        #------------------------------------------------------------------------------------------------------------------

                        #------------------------------------------------------------------------------------------------------------------
                        # download_output_data
                        data_out = []
                        if ana_step._kernel._download_output_data is not None:
                            if isinstance(ana_step._kernel._download_output_data,list):
                                pass
                            else:
                                ana_step._kernel._download_output_data = [ana_step._kernel._download_output_data]
                            for i in range(0,len(ana_step._kernel._download_output_data)):
                                var=resolve_placeholder_vars(working_dirs, a_instance, iteration, pattern._simulation_instances, pattern._analysis_instances, "analysis", ana_step._kernel._download_output_data[i])
                                if len(var.split('>')) > 1:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': var.split('>')[1].strip()
                                        }
                                else:
                                    temp = {
                                            'source': var.split('>')[0].strip(),
                                            'target': os.path.basename(var.split('>')[0].strip())
                                        }
                                data_out.append(temp)

                        if cud.output_staging is None:
                            cud.output_staging = data_out
                        else:
                            cud.output_staging += data_out
                        #------------------------------------------------------------------------------------------------------------------


                        if ana_step.cores is not None:
                            cud.cores = ana_step.cores

                        a_units.append(cud)

                        if ana_step.get_instance_type == 'single':
                            break

                    self.get_logger().debug("Created analysis CU: {0}.".format(cud.as_dict()))
                    
                    self.get_logger().info("Submitted tasks for analysis iteration {0}.".format(iteration))
                    self.get_logger().info("Waiting for analysis tasks in iteration {0}/kernel {1}: {2} to complete.".format(iteration,kern_step+1,ana_step.name))

                    self._reporter.info("\nIteration {0}: Waiting for analysis tasks: {1} to complete".format(iteration,ana_step.name))
                    if profiling == 1:
                        probe_ana_wait = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['kernel_{0}'.format(kern_step)]['wait_time'] = probe_ana_wait


                    a_cus = resource._umgr.submit_units(a_units)
                    all_cus.extend(a_cus)
                    all_ana_cus.extend(a_cus)

                    uids = [cu.uid for cu in a_cus]
                    resource._umgr.wait_units(uids)

                    if profiling == 1:
                        probe_ana_res = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['kernel_{0}'.format(kern_step)]['res_time'] = probe_ana_res
                        
                    self.get_logger().info("Analysis in iteration {0}/kernel {1}: {2} completed.".format(iteration,kern_step+1,ana_step.name))

                    failed_units = ""
                    for unit in a_cus:
                        if unit.state != radical.pilot.DONE:
                            failed_units += " * Analysis task {0} failed with an error: {1}\n".format(unit.uid, unit.stderr)

                    if profiling == 1:
                        probe_ana_done = datetime.datetime.now()
                        enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['kernel_{0}'.format(kern_step)]['stop_time'] = probe_ana_done

                    self._reporter.ok('>> done')

                if profiling == 1:
                    probe_post_ana_start = datetime.datetime.now()
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['post'] = od()
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['post']['start_time'] = probe_post_ana_start

                i = 0
                for cu in a_cus:
                    i += 1
                    working_dirs['iteration_{0}'.format(iteration)]['analysis_{0}'.format(i)] = saga.Url(cu.working_directory).path

                if profiling == 1:
                    probe_post_ana_end = datetime.datetime.now()
                    enmd_overhead_dict['iter_{0}'.format(iteration)]['ana']['post']['stop_time'] = probe_post_ana_end
                    cu_dict['iter_{0}'.format(iteration)]['ana'] = all_ana_cus

            self._reporter.header('Pattern execution successfully finished')

            if profiling == 1:

                #Pattern overhead logging
                title = "iteration,step,kernel,probe,timestamp"
                f1 = open('enmd_pat_overhead.csv','w')
                f1.write(title + "\n\n")
                iter = 'None'
                step = 'pre_loop'
                kern = 'None'
                for key,val in enmd_overhead_dict['preloop'].items():
                    probe = key
                    timestamp = val
                    entry = '{0},{1},{2},{3},{4}\n'.format(iter,step,kern,probe,timestamp)
                    f1.write(entry)

                iters = pattern.iterations

                for i in range(1,iters+1):
                    iter = 'iter_{0}'.format(i)
                    for key1,val1 in enmd_overhead_dict[iter].items():
                        step = key1
                        for key2,val2 in val1.items():
                            kern = key2
                            for key3,val3 in val2.items():
                                probe = key3
                                timestamp = val3
                                entry = '{0},{1},{2},{3},{4}\n'.format(iter.split('_')[1],step,kern,probe,timestamp)
                                f1.write(entry)

                f1.close()

                #CU data logging
                title = "uid, iter, step, uid, step, Scheduling, StagingInput, AgentStagingInputPending, AgentStagingInput, AllocatingPending, Allocating, ExecutingPending, Executing, AgentStagingOutputPending, AgentStagingOutput, PendingOutputStaging, StagingOutput, Done"
                f2 = open("execution_profile_{mysession}.csv".format(mysession=resource._session.uid),'w')
                f2.write(title + "\n\n")
                iter = 'None'
                step = 'pre_loop'

                if step in cu_dict:
                    cu = cu_dict['pre_loop']

                    st_data = {}
                    for st in cu.state_history:
                        st_dict = st.as_dict()
                        st_data["{0}".format( st_dict["state"] )] = {}
                        st_data["{0}".format( st_dict["state"] )] = st_dict["timestamp"]

                    states = ['Scheduling,' 
                                                'StagingInput', 'AgentStagingInputPending', 'AgentStagingInput',
                                                'AllocatingPending', 'Allocating', 
                                                'ExecutingPending', 'Executing', 
                                                'AgentStagingOutputPending', 'AgentStagingOutput', 'PendingOutputStaging', 
                                                'StagingOutput', 
                                                'Done']
                                                
                    for state in states:
                        if (state in st_data) is False:
                            st_data[state] = None

                    line = "{uid}, {iter}, {step}, {Scheduling}, {StagingInput}, {AgentStagingInputPending}, {AgentStagingInput}, {AllocatingPending}, {Allocating}, {ExecutingPending},{Executing}, {AgentStagingOutputPending}, {AgentStagingOutput}, {PendingOutputStaging}, {StagingOutput}, {Done}".format(
                            uid=cu.uid,
                            iter=0,
                            step='pre_loop',
                            Scheduling=(st_data['Scheduling']),
                                    StagingInput=(st_data['StagingInput']),
                                    AgentStagingInputPending=(st_data['AgentStagingInputPending']),
                                    AgentStagingInput=(st_data['AgentStagingInput']),
                                    AllocatingPending=(st_data['AllocatingPending']),
                                    Allocating=(st_data['Allocating']),
                                    ExecutingPending=(st_data['ExecutingPending']),
                                    Executing=(st_data['Executing']),
                                    AgentStagingOutputPending=(st_data['AgentStagingOutputPending']),
                                    AgentStagingOutput=(st_data['AgentStagingOutput']),
                                    PendingOutputStaging=(st_data['PendingOutputStaging']),
                                    StagingOutput=(st_data['StagingOutput']),
                                    Done=(st_data['Done']))
                    f2.write(line + '\n')
                else:
                    print 'No pre_loop step in the pattern'

                for i in range(1,iters+1):
                    iter = 'iter_{0}'.format(i)
                    for key,val in cu_dict[iter].items():
                        step = key
                        cus = val

                        if step == 'sim':
                            for cu in cus:
                                st_data = {}
                                for st in cu.state_history:
                                    st_dict = st.as_dict()
                                    st_data["{0}".format( st_dict["state"] )] = {}
                                    st_data["{0}".format( st_dict["state"] )] = st_dict["timestamp"]

                                states = ['Scheduling,' 
                                                'StagingInput', 'AgentStagingInputPending', 'AgentStagingInput',
                                                'AllocatingPending', 'Allocating', 
                                                'ExecutingPending', 'Executing', 
                                                'AgentStagingOutputPending', 'AgentStagingOutput', 'PendingOutputStaging', 
                                                'StagingOutput', 
                                                'Done']

                                for state in states:
                                    if (state in st_data) is False:
                                        st_data[state] = None

                                line = "{uid}, {iter}, {step}, {Scheduling}, {StagingInput}, {AgentStagingInputPending}, {AgentStagingInput}, {AllocatingPending}, {Allocating}, {ExecutingPending},{Executing}, {AgentStagingOutputPending}, {AgentStagingOutput}, {PendingOutputStaging}, {StagingOutput}, {Done}".format(
                                    uid=cu.uid,
                                    iter=iter.split('_')[1],
                                    step=step,
                                    Scheduling=(st_data['Scheduling']),
                                    StagingInput=(st_data['StagingInput']),
                                    AgentStagingInputPending=(st_data['AgentStagingInputPending']),
                                    AgentStagingInput=(st_data['AgentStagingInput']),
                                    AllocatingPending=(st_data['AllocatingPending']),
                                    Allocating=(st_data['Allocating']),
                                    ExecutingPending=(st_data['ExecutingPending']),
                                    Executing=(st_data['Executing']),
                                    AgentStagingOutputPending=(st_data['AgentStagingOutputPending']),
                                    AgentStagingOutput=(st_data['AgentStagingOutput']),
                                    PendingOutputStaging=(st_data['PendingOutputStaging']),
                                    StagingOutput=(st_data['StagingOutput']),
                                    Done=(st_data['Done']))

                                f2.write(line + '\n')

                        elif step == 'ana':
                            for cu in cus:
                                st_data = {}
                                for st in cu.state_history:
                                    st_dict = st.as_dict()
                                    st_data["{0}".format( st_dict["state"] )] = {}
                                    st_data["{0}".format( st_dict["state"] )] = st_dict["timestamp"]


                                states = ['Scheduling,' 
                                                'StagingInput', 'AgentStagingInputPending', 'AgentStagingInput',
                                                'AllocatingPending', 'Allocating', 
                                                'ExecutingPending', 'Executing', 
                                                'AgentStagingOutputPending', 'AgentStagingOutput', 'PendingOutputStaging', 
                                                'StagingOutput', 
                                                'Done']

                                for state in states:
                                    if (state in st_data) is False:
                                        st_data[state] = None

                                line = "{uid}, {iter}, {step}, {Scheduling}, {StagingInput}, {AgentStagingInputPending}, {AgentStagingInput}, {AllocatingPending}, {Allocating}, {ExecutingPending},{Executing}, {AgentStagingOutputPending}, {AgentStagingOutput}, {PendingOutputStaging}, {StagingOutput}, {Done}".format(
                                    uid=cu.uid,
                                    iter=iter.split('_')[1],
                                    step=step,
                                    Scheduling=(st_data['Scheduling']),
                                    StagingInput=(st_data['StagingInput']),
                                    AgentStagingInputPending=(st_data['AgentStagingInputPending']),
                                    AgentStagingInput=(st_data['AgentStagingInput']),
                                    AllocatingPending=(st_data['AllocatingPending']),
                                    Allocating=(st_data['Allocating']),
                                    ExecutingPending=(st_data['ExecutingPending']),
                                    Executing=(st_data['Executing']),
                                    AgentStagingOutputPending=(st_data['AgentStagingOutputPending']),
                                    AgentStagingOutput=(st_data['AgentStagingOutput']),
                                    PendingOutputStaging=(st_data['PendingOutputStaging']),
                                    StagingOutput=(st_data['StagingOutput']),
                                    Done=(st_data['Done']))

                                f2.write(line + '\n')

                f2.close()

        except KeyboardInterrupt:

            self._reporter.error('Execution interupted')
            traceback.print_exc()

