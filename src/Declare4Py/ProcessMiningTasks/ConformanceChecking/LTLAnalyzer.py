from __future__ import annotations

import multiprocessing
import pdb
import time

from pm4py.objects.log.obj import Trace
from pythomata.impl.symbolic import SymbolicDFA
from pylogics.parsers import parse_ltl
from src.Declare4Py.D4PyEventLog import D4PyEventLog
from src.Declare4Py.ProcessMiningTasks.AbstractConformanceChecking import AbstractConformanceChecking
from src.Declare4Py.ProcessModels.LTLModel import LTLModel
from src.Declare4Py.Utils.utils import Utils
from logaut import ltl2dfa
from functools import reduce
import pandas

"""
Provides basic conformance checking functionalities
"""


class LTLAnalyzer(AbstractConformanceChecking):

    def __init__(self, log: D4PyEventLog, *args):
        """

        Args:
            log: D4PYEventLog
            *args: A LTLModel or a list of LTLModels
        """
        if isinstance(args[0], LTLModel):
            super().__init__(log, args[0])
        else:
            self.log = log
            self.list_LTLModels = args[0]

    @staticmethod
    def run_single_trace(trace: Trace, dfa: SymbolicDFA, backend, attribute_type: [str] = ['concept:name']):
        current_states = {dfa.initial_state}
        for event in trace:
            temp = dict()
            for attribute in attribute_type:
                symbol = event[attribute]
                symbol = Utils.parse_parenthesis(symbol)
                symbol = Utils.encode_attribute_type(attribute) + "_" + symbol
                symbol = Utils.parse_activity(symbol)
                if backend == 'lydia':
                    symbol = symbol.lower()
                else:
                    symbol = symbol.upper()
                temp[symbol] = True

                current_states = reduce(
                    set.union,
                    map(lambda x: dfa.get_successors(x, temp), current_states),
                    set(),
                )

        is_accepted = any(dfa.is_accepting(state) for state in current_states)
        return is_accepted

    @staticmethod
    def run_single_trace_par(args):
        trace, dfa, attributes = args
        current_states = {dfa.initial_state}

        for event in trace:
            temp = dict()
            for attribute in attributes:
                symbol = event[attribute]
                symbol = Utils.parse_parenthesis(symbol)
                symbol = Utils.encode_attribute_type(attribute) + "_" + symbol
                symbol = Utils.parse_activity(symbol)
                symbol = symbol.lower()
                temp[symbol] = True

                current_states = reduce(
                    set.union,
                    map(lambda x: dfa.get_successors(x, temp), current_states),
                    set(),
                )

        is_accepted = any(dfa.is_accepting(state) for state in current_states)
        return trace.attributes['concept:name'], is_accepted

    @staticmethod
    def run_single_trace_par_MM(args):
        trace, list_LTLModels = args
        is_accepted = True
        for unpacked_model in list_LTLModels:
            backend2dfa = unpacked_model[0]
            dfa = unpacked_model[1]
            attributes = unpacked_model[2]

            # Run single trace
            current_states = {dfa.initial_state}
            for event in trace:
                temp = dict()
                for attribute in attributes:
                    symbol = event[attribute]
                    symbol = Utils.parse_parenthesis(symbol)
                    symbol = Utils.encode_attribute_type(attribute) + "_" + symbol
                    symbol = Utils.parse_activity(symbol)
                    if backend2dfa == 'lydia':
                        symbol = symbol.lower()
                    else:
                        symbol = symbol.upper()
                    temp[symbol] = True

                    current_states = reduce(
                        set.union,
                        map(lambda x: dfa.get_successors(x, temp), current_states),
                        set(),
                    )

            is_accepted = any(dfa.is_accepting(state) for state in current_states)

            if not is_accepted:
                return trace.attributes['concept:name'], is_accepted
        return trace.attributes['concept:name'], is_accepted

    def run(self, jobs: int = 1, minimize_automaton: bool = True) -> pandas.DataFrame:
        """
        Performs conformance checking for the provided event log and an input LTL model.

        Args:
            jobs:
            minimize_automaton:

        Returns:
            DataFrame: A pandas Dataframe containing the id of the traces and the result of the conformance check

        """
        workers = jobs

        if jobs == 1 or jobs == 0:
            sequential = True
        elif jobs == -1:
            workers = multiprocessing.cpu_count()
            sequential = False
        elif jobs > 1:
            workers = jobs
            sequential = False
        else:
            raise RuntimeError(f"{jobs} not a valid number of jobs. Allowed values goes from -1.")

        backend2dfa = self.process_model.backend
        dfa = ltl2dfa(self.process_model.parsed_formula, backend=backend2dfa)  # lydia

        if minimize_automaton:
            dfa = dfa.minimize()
        g_log = self.event_log.get_log()
        attributes = self.process_model.attribute_type
        if sequential:
            results = []
            for trace in g_log:
                is_accepted = self.run_single_trace(trace, dfa, backend2dfa, attributes)
                results.append([trace.attributes[self.event_log.activity_key], is_accepted])
        else:
            traces = g_log._list
            with multiprocessing.Pool(processes=workers) as pool:
                results = pool.map(self.run_single_trace_par, zip(traces, [dfa] * len(traces),
                                                                  [attributes] * len(traces)))
        return pandas.DataFrame(results, columns=[self.event_log.case_id_key, "accepted"])

    def run_multiple_models(self, jobs: int = 1, minimize_automaton: bool = True) -> pandas.DataFrame:
        """
        Performs conformance checking for the provided event log and an input LTL models.

        Args:
            jobs:
            minimize_automaton:

        Returns:
            DataFrame: A pandas Dataframe containing the id of the traces and the result of the conformance check

        """
        workers = jobs

        if jobs == 1 or jobs == 0:
            sequential = True
        elif jobs == -1:
            workers = multiprocessing.cpu_count()
            sequential = False
        elif jobs > 1:
            workers = jobs
            sequential = False
        else:
            raise RuntimeError(f"{jobs} not a valid number of jobs. Allowed values goes from -1.")

        g_log = self.log.get_log()
        results = {}
        if sequential:
            for id_model, model in enumerate(self.list_LTLModels):
                n = len(g_log)
                if n > 0:
                    temp_list = []
                    backend2dfa = model.backend
                    dfa = ltl2dfa(model.parsed_formula, backend=model.backend)
                    if minimize_automaton:
                        dfa = dfa.minimize()

                    attributes = model.attribute_type
                    for trace in g_log:
                        is_accepted = self.run_single_trace(trace, dfa, backend2dfa, attributes)
                        if is_accepted:
                            temp_list.append(trace)
                        results[trace.attributes[self.log.activity_key]] = is_accepted
                    n = len(temp_list)
                    g_log = temp_list
                if n == 0:
                    break
            results = results.items()
        else:
            traces = g_log._list
            with multiprocessing.Pool(processes=workers) as pool:
                tmp_model_list = []
                for model in self.list_LTLModels:
                    dfa = ltl2dfa(model.parsed_formula, backend=model.backend)
                    if minimize_automaton:
                        dfa = dfa.minimize()
                    tmp_model_list.append((model.backend, dfa, model.attribute_type))

                results = pool.map(self.run_single_trace_par_MM, zip(traces, [tmp_model_list]*len(traces)))

        return pandas.DataFrame(results, columns=[self.log.case_id_key, "accepted"])

    def run_aggregate(self) -> pandas.DataFrame:
        """
        Performs conformance checking for the provided event log and an input LTL model.

        Returns:
            A pandas Dataframe containing the id of the traces and the result of the conformance check
        """

        if self.event_log is None:
            raise RuntimeError("You must load the log before checking the model.")
        if self.process_model is None:
            raise RuntimeError("You must load the LTL model before checking the model.")
        dfa = ltl2dfa(self.process_model.parsed_formula, backend=self.process_model.backend)
        dfa = dfa.minimize()
        group = self.event_log.groupby(self.event_log.case_id_key, as_index=True)
        results = group[self.event_log.activity_key].aggregate(self.run_single_trace, dfa=dfa, engine='cython')

        return pandas.DataFrame(results, columns=[self.event_log.case_id_key, "accepted"])