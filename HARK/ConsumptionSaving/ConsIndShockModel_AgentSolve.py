# -*- coding: utf-8 -*-
from HARK.core import (_log, core_check_condition)

from scipy.optimize import newton as find_zero_newton
from numpy import dot as E_dot  # easier to type
from numpy.testing import assert_approx_equal as assert_approx_equal
import numpy as np
from copy import deepcopy
from builtins import (str, breakpoint)
from types import SimpleNamespace
from IPython.lib.pretty import pprint
from HARK.ConsumptionSaving.ConsIndShockModel_Both import (
    def_utility, def_value_funcs)
from HARK.distribution import (calc_expectation, calc_expectation_of_array)
from HARK.interpolation import (CubicInterp, LowerEnvelope, LinearInterp,
                                ValueFuncCRRA, MargValueFuncCRRA,
                                MargMargValueFuncCRRA)
from HARK import NullFunc
from HARK.ConsumptionSaving.ConsIndShockModelOld \
    import ConsumerSolution as ConsumerSolutionOlder


class Built(SimpleNamespace):
    """
    Objects built by solvers during course of solution.
    """
# TODO: Move (to core.py) when vetted/agreed
    pass


class Parameters(SimpleNamespace):
    """
    Parameters (both as passed, and as exposed for convenience). But not modified.
    """
# TODO: Move (to core.py) when vetted/agreed
    pass


class Expectations(SimpleNamespace):
    """
    Expectations across realization of stochastic shocks.
    """
# TODO: Move (to core.py) when vetted/agreed
    pass


class Ante_Choice(SimpleNamespace):
    """
    Expectations before choices or shocks
    """


class Post_Choice(SimpleNamespace):
    """
    Expectations after choices before shocks

    """


class Successor(SimpleNamespace):
    """
    Objects retrieved from successor to the stage
    referenced in "self." Should contain everything needed to reconstruct
    solution to problem of self even if solution_next is not present.
    """
# TODO: Move (to core.py) when vetted/agreed
    pass


__all__ = [
    "ConsumerSolutionOlder",
    "ConsumerSolution",
    "ConsumerSolutionOneStateCRRA",
    "ConsPerfForesightSolverEOP",
    "ConsPerfForesightSolver",
    "ConsIndShockSetupEOP",
    "ConsIndShockSetup",
    "ConsIndShockSolverBasicEOP",
    "ConsIndShockSolverBasic",
    "ConsIndShockSolverEOP",
    "ConsIndShockSolver",
    "ConsIndShockSetupEOP",
    "ConsIndShockSetup",
]


class ConsumerSolution(ConsumerSolutionOlder):
    __doc__ = ConsumerSolutionOlder.__doc__
    __doc__ += """
    stge_kind : dict
        Dictionary with info about this stage
        One built-in entry keeps track of the nature of the stage:
            {'iter_status':'finished'}: Stopping requirements are satisfied
                If stopping requirements are satisfied, {'tolerance':tolerance}
                should exist recording what convergence tolerance was satisfied
            {'iter_status':'iterator'}: Solution during iteration
                solution[0].distance_last records the last distance
            {'iter_status':'terminal_pseudo'}: Bare-bones terminal period
                Does not contain all the info needed to begin solution
                Solver will augment and replace it with 'iterator' stage
        Other uses include keeping track of the nature of the next stage
    step_info : dict
        Dictionary with info about this step of the solution process
    parameters_solver : dict
        Stores the parameters with which the solver was called
    completed_cycles : integer
        The number of cycles of the model that have been solved before this call
    """

# CDC 20210426: vPfunc was a bad choice for distance; here we change
# to cFunc but doing so will require recalibrating some of our tests
#    distance_criteria = ["vPfunc"]  # Bad b/c vP(0)=inf; should use cFunc
#    distance_criteria = ["vFunc.dm"]  # Bad b/c vP(0)=inf; should use cFunc
#    distance_criteria = ["mNrmTrg"]  # mNrmTrg is better choice if GICNrm holds
    distance_criteria = ["cFunc"]  # cFunc if the GIC fails

    def __init__(self, *args,
                 # TODO: These new items should eventually become part of the default
                 stge_kind={'iter_status': 'not initialized'},
                 completed_cycles=0,
                 parameters_solver=None,
                 vAdd=None,
                 **kwds):
        ConsumerSolutionOlder.__init__(self, *args, **kwds)

        # Most previous "whiteboard" content is now on "bilt"
        bilt = self.bilt = Built()
        pars = self.pars = Parameters()
        pars.about = {'Parameters exogenously given'}
        self.E_t = Expectations()  # Namespace for expectations
        self.E_t.ante = Ante_Choice()  # Before choices or shocks
        self.E_t.post = Post_Choice()  # After choices, before shocks

        eqns = self.xfer_crnt_post_to_next_ante = {}
        eqns.update({'RNrm': 'Rfree / (PermGroFac * permShk)'})
        eqns.update({'bNrm': 'aNrm * RNrm'})
        eqns.update({'yNrm': 'tranShk'})
        eqns.update({'mNrm': 'bNrm + tranShk'})

        bilt.recursive = \
            {'cFunc', 'vFunc',  'vPfunc', 'vPPfunc',  'vFuncNvrs',
             'vFunc.dm', 'vFunc.dm.dm',
             'u', 'uP', 'uPP', 'uPinv', 'uPinvP', 'uinvP', 'uinv', 'hNrm',
             'mNrmMin', 'MPCmin', 'MPCmax', 'BoroCnstNat', 'CRRA', 'vAdd'
             }

        # Store recursive stuff in bilt namespace
        exclude = {''}  # Allow things that should be excluded
        for key in (k for k in bilt.recursive if k not in exclude):  #
            if hasattr(self, key):
                setattr(bilt, key, self.__dict__[key])

        # Stuff added; should (ultimately) be incorporated in ConsumerSolution
        bilt.stge_kind = stge_kind
        bilt.completed_cycles = completed_cycles
        bilt.parameters_solver = parameters_solver
        bilt.vAdd = vAdd


class ConsumerSolutionOneStateCRRA(ConsumerSolution):
    """
    Specialize ConsumerSolution in two ways:

        * Constant Relative Risk Aversion (CRRA) utility
        * Geometric Discounting of Time Separable Utility

    along with a standard set of restrictions on the parameter values of the
    model (like, the time preference factor must be positive).  Under various
    combinations of these assumptions, various conditions imply different
    conclusions.  The suite of minimal restrictions is always evaluated.
    Conditions are evaluated using the `check_conditions` method.  (Further
    information about the conditions can be found in the documentation for
    that method.)  For convenience, we repeat below the documentation for the
    parent ConsumerSolution of this class, all of which applies here.
    """
    __doc__ += ConsumerSolution.__doc__

    time_vary_ = ["LivPrb",  # Age-varying death rates can match mortality data
                  "PermGroFac"]  # Age-varying income growth to match lifecycle
    time_inv_ = ["CRRA", "Rfree", "DiscFac", "BoroCnstArt"]
    state_vars = ['pLvl',  # Initial idiosyncratic permanent income; for sims
                  'PlvlAgg',  # Aggregate permanent income; macro models
                  'bNrm',  # Bank balances beginning of period (pLvl normed)
                  'mNrm',  # Market resources (b + income - normed by pLvl
                  "aNrm"]  # Assets after all actions (pLvl normed)
    shock_vars_ = []

    def __init__(self, *args,
                 CRRA=2.0,
                 **kwds):

        ConsumerSolution.__init__(self, *args, **kwds)
        # We are now in position to define some elements of the
        # dolo representation of the model
#        dolo = self.dolo
        # # These will be updated when more specific assumptions are made
#        dolo.model_name = 'ConsumerSolutionOneStateCRRA'
#        dolo.symbols = {'states': ['mNrm'],
#                        'controls': ['cNrm'],
#                        'parameters': ['ρ', 'β', 'Π', 'Rfree', 'Γ'],
#                        'expectations': ['Euler_cNrm'],
#                        'transition': ['DBC_mNrm'],
#                        }

        # Instantiate CRRA utility
        self = def_utility(self, CRRA)

        # These things have been moved to bilt to declutter whiteboard
        del self.mNrmMin
        del self.hNrm
        del self.MPCmin
        del self.MPCmax
        del self.vFunc
        del self.cFunc
        del self.vPfunc
        del self.vPPfunc

    def check_conditions(self, soln_crnt, verbose=None):
        """
        Checks whether the instance's type satisfies the:

        ================================================================
        Acronym        Condition
        ================================================================
        AIC           Absolute Impatience Condition
        RIC           Return Impatience Condition
        GIC           Growth Impatience Condition
        GICLiv        GIC adjusting for constant probability of mortality
        GICNrm        GIC adjusted for uncertainty in permanent income
        FHWC          Finite Human Wealth Condition
        FVAC          Finite Value of Autarky Condition
        ================================================================

        Depending on the configuration of parameter values, some combination of
        these conditions must be satisfied in order for the problem to have
        a nondegenerate soln_crnt. To check which conditions are required,
        in the verbose mode, a reference to the relevant theoretical literature
        is made.

        Parameters
        ----------
        verbose : int
        Specifies different levels of verbosity of feedback. When False, it only reports whether the
        instance's type fails to satisfy a particular condition. When True, it reports all results, i.e.
        the factor values for all conditions.

        soln_crnt : ConsumerSolution
        Solution to the problem described by information
        for the current stage found in bilt and the succeeding stage found
        in folw.

        Returns
        -------
        None
        """
        soln_crnt.bilt.conditions = {}  # Keep track of truth of conditions
        soln_crnt.bilt.degenerate = False  # True: solution is degenerate

        if not hasattr(self, 'verbose'):  # If verbose not set yet
            verbose = 0
        else:
            verbose = verbose if verbose is None else verbose

        msg = '\nFor a model with the following parameter values:\n'
        msg = msg+'\n'+str(soln_crnt.bilt.parameters_solver)+'\n'

        if verbose >= 2:
            _log.info(msg)
            _log.info(str(soln_crnt.bilt.parameters_solver))
            np.set_printoptions(threshold=20)  # Don't print huge output
            for key in soln_crnt.bilt.parameters_solver.keys():
                print('\t'+key+': ', end='')
                pprint(soln_crnt.bilt.parameters_solver[key])
            msg = '\nThe following results hold:\n'
            _log.info(msg)

        soln_crnt.check_AIC(soln_crnt, verbose)
        soln_crnt.check_FHWC(soln_crnt, verbose)
        soln_crnt.check_RIC(soln_crnt, verbose)
        soln_crnt.check_GICRaw(soln_crnt, verbose)
        soln_crnt.check_GICNrm(soln_crnt, verbose)
        soln_crnt.check_GICLiv(soln_crnt, verbose)
        soln_crnt.check_FVAC(soln_crnt, verbose)

        # degenerate flag is true if the model has no nondegenerate solution
        if hasattr(soln_crnt.bilt, "BoroCnstArt") \
                and soln_crnt.pars.BoroCnstArt is not None:
            soln_crnt.degenerate = not soln_crnt.bilt.RIC
            # If BoroCnstArt exists but RIC fails, limiting soln is c(m)=0
        else:  # No constraint; not degenerate if neither c(m)=0 or \infty
            soln_crnt.degenerate = \
                not soln_crnt.bilt.RIC or not soln_crnt.bilt.FHWC

    def check_AIC(self, stge, verbose=None):
        """
        Evaluate and report on the Absolute Impatience Condition
        """
        name = "AIC"

        def test(stge): return stge.bilt.APF < 1

        messages = {
            True: "\n\nThe Absolute Patience Factor for the supplied parameter values, APF={0.APF}, satisfies the Absolute Impatience Condition (AIC), which requires APF < 1:\n    "+stge.bilt.AIC_fcts['urlhandle'],
            False: "\n\nThe Absolute Patience Factor for the supplied parameter values, APF={0.APF}, violates the Absolute Impatience Condition (AIC), which requires APF < 1:\n    "+stge.bilt.AIC_fcts['urlhandle']
        }
        verbose_messages = {
            True: "\n  Because the APF < 1,  the absolute amount of consumption is expected to fall over time.  \n",
            False: "\n  Because the APF > 1, the absolute amount of consumption is expected to grow over time.  \n",
        }

        stge.bilt.AIC = core_check_condition(name, test, messages, verbose,
                                             verbose_messages, "APF", stge)

    def check_FVAC(self, stge, verbose=None):
        """
        Evaluate and report on the Finite Value of Autarky Condition
        """
        name = "FVAC"
        def test(stge): return stge.bilt.FVAF < 1

        messages = {
            True: "\n\nThe Finite Value of Autarky Factor for the supplied parameter values, FVAF={0.FVAF}, satisfies the Finite Value of Autarky Condition, which requires FVAF < 1:\n    "+stge.bilt.FVAC_fcts['urlhandle'],
            False: "\n\nThe Finite Value of Autarky Factor for the supplied parameter values, FVAF={0.FVAF}, violates the Finite Value of Autarky Condition, which requires FVAF:\n    "+stge.bilt.FVAC_fcts['urlhandle']
        }
        verbose_messages = {
            True: "\n  Therefore, a nondegenerate solution exists if the RIC also holds. ("+stge.bilt.FVAC_fcts['urlhandle']+")\n",
            False: "\n  Therefore, a nondegenerate solution exits if the RIC holds, but will not exist if the RIC fails unless the FHWC also fails.\n",
        }

        stge.bilt.FVAC = core_check_condition(name, test, messages, verbose,
                                              verbose_messages, "FVAF", stge)

    def check_GICRaw(self, stge, verbose=None):
        """
        Evaluate and report on the Growth Impatience Condition
        """
        name = "GICRaw"

        def test(stge): return stge.bilt.GPFRaw < 1

        messages = {
            True: "\n\nThe Growth Patience Factor for the supplied parameter values, GPF={0.GPFRaw}, satisfies the Growth Impatience Condition (GIC), which requires GPF < 1:\n    "+stge.bilt.GICRaw_fcts['urlhandle'],
            False: "\n\nThe Growth Patience Factor for the supplied parameter values, GPF={0.GPFRaw}, violates the Growth Impatience Condition (GIC), which requires GPF < 1:\n    "+stge.bilt.GICRaw_fcts['urlhandle'],
        }
        verbose_messages = {
            True: "\n  Therefore,  for a perfect foresight consumer, the ratio of individual wealth to permanent income is expected to fall indefinitely.    \n",
            False: "\n  Therefore, for a perfect foresight consumer whose parameters satisfy the FHWC, the ratio of individual wealth to permanent income is expected to rise toward infinity. \n"
        }
        stge.bilt.GICRaw = core_check_condition(name, test, messages, verbose,
                                                verbose_messages, "GPFRaw", stge)

    def check_GICLiv(self, stge, verbose=None):
        name = "GICLiv"

        def test(stge): return stge.bilt.GPFLiv < 1

        messages = {
            True: "\n\nThe Mortality Adjusted Aggregate Growth Patience Factor for the supplied parameter values, GPFLiv={0.GPFLiv}, satisfies the Mortality Adjusted Aggregate Growth Impatience Condition (GICLiv):\n    "+stge.bilt.GPFLiv_fcts['urlhandle'],
            False: "\n\nThe Mortality Adjusted Aggregate Growth Patience Factor for the supplied parameter values, GPFLiv={0.GPFLiv}, violates the Mortality Adjusted Aggregate Growth Impatience Condition (GICLiv):\n    "+stge.bilt.GPFLiv_fcts['urlhandle'],
        }
        verbose_messages = {
            True: "\n  Therefore, a target level of the ratio of aggregate market resources to aggregate permanent income exists ("+stge.bilt.GPFLiv_fcts['urlhandle']+")\n",
            False: "\n  Therefore, a target ratio of aggregate resources to aggregate permanent income may not exist ("+stge.bilt.GPFLiv_fcts['urlhandle']+")\n",
        }
#        stge.GICLiv =
        stge.bilt.GICLiv = core_check_condition(name, test, messages, verbose,
                                                verbose_messages, "GPFLiv", stge)

    def check_RIC(self, stge, verbose=None):
        """
        Evaluate and report on the Return Impatience Condition
        """

        name = "RIC"

        def test(stge): return stge.bilt.RPF < 1

        messages = {
            True: "\n\nThe Return Patience Factor for the supplied parameter values, RPF= {0.RPF}, satisfies the Return Impatience Condition (RIC), which requires RPF < 1:\n    "+stge.bilt.RPF_fcts['urlhandle'],
            False: "\n\nThe Return Patience Factor for the supplied parameter values, RPF= {0.RPF}, violates the Return Impatience Condition (RIC), which requires RPF < 1:\n    "+stge.bilt.RPF_fcts['urlhandle'],
        }
        verbose_messages = {
            True: "\n  Therefore, the limiting consumption function is not c(m)=0 for all m\n",
            False: "\n  Therefore, if the FHWC is satisfied, the limiting consumption function is c(m)=0 for all m.\n",
        }
#        stge.RIC =
        stge.bilt.RIC = core_check_condition(name, test, messages, verbose,
                                             verbose_messages, "RPF", stge)

    def check_FHWC(self, stge, verbose=None):
        """
        Evaluate and report on the Finite Human Wealth Condition
        """
        name = "FHWC"

        def test(stge): return stge.bilt.FHWF < 1

        messages = {
            True: "\n\nThe Finite Human Wealth Factor value for the supplied parameter values, FHWF={0.FHWF}, satisfies the Finite Human Wealth Condition (FHWC), which requires FHWF < 1:\n    "+stge.bilt.FHWC_fcts['urlhandle'],
            False: "\n\nThe Finite Human Wealth Factor value for the supplied parameter values, FHWF={0.FHWF}, violates the Finite Human Wealth Condition (FHWC), which requires FHWF < 1:\n    "+stge.bilt.FHWC_fcts['urlhandle'],
        }
        verbose_messages = {
            True: "\n  Therefore, the limiting consumption function is not c(m)=Infinity.\n  Human wealth normalized by permanent income is {0.hNrmInf}.\n",
            False: "\n  Therefore, the limiting consumption function is c(m)=Infinity for all m unless the RIC is also violated.\n  If both FHWC and RIC fail and the consumer faces a liquidity constraint, the limiting consumption function is nondegenerate but has a limiting slope of 0. ("+stge.bilt.FHWC_fcts['urlhandle']+")\n",
        }
#        stge.FHWC =
        stge.bilt.FHWC = core_check_condition(name, test, messages, verbose,
                                              verbose_messages, "FHWF", stge)

    def check_GICNrm(self, stge, verbose=None):
        """
        Check Normalized Growth Patience Factor.
        """
        if not hasattr(stge.pars, 'IncShkDstn'):
            return  # GICNrm is same as GIC for PF consumer

        name = "GICNrm"

        def test(stge): return stge.bilt.GPFNrm <= 1

        messages = {
            True: "\n\nThe Normalized Growth Patience Factor GPFNrm for the supplied parameter values, GPFNrm={0.GPFNrm}, satisfies the Normalized Growth Impatience Condition (GICNrm), which requires GPFNrm < 1:\n    "+stge.bilt.GICNrm_fcts['urlhandle'],
            False: "\n\nThe Normalized Growth Patience Factor GPFNrm for the supplied parameter values, GPFNrm={0.GPFNrm}, violates the Normalized Growth Impatience Condition (GICNrm), which requires GPFNrm < 1:\n    "+stge.bilt.GICNrm_fcts['urlhandle'],
        }
        verbose_messages = {
            True: "\n  Therefore, a target level of the individual market resources ratio m exists.",
            False: "\n  Therefore, a target ratio of individual market resources to individual permanent income does not exist.  ("+stge.bilt.GICNrm_fcts['urlhandle']+")\n",
        }

        stge.bilt.GICNrm = core_check_condition(name, test, messages, verbose,
                                                verbose_messages, "GPFNrm", stge)

    def check_WRIC(self, stge, verbose=None):
        """
        Evaluate and report on the Weak Return Impatience Condition
        [url]/  # WRIC modified to incorporate LivPrb
        """

        if not hasattr(stge, 'IncShkDstn'):
            return  # WRIC is same as RIC for PF consumer

        name = "WRIC"

        def test(stge): return stge.bilt.WRPF <= 1

        messages = {
            True: "\n\nThe Weak Return Patience Factor value for the supplied parameter values, WRPF={0.WRPF}, satisfies the Weak Return Impatience Condition, which requires WRPF < 1:\n    "+stge.bilt.WRIC_fcts['urlhandle'],
            False: "\n\nThe Weak Return Patience Factor value for the supplied parameter values, WRPF={0.WRPF}, violates the Weak Return Impatience Condition, which requires WRPF < 1:\n    "+stge.bilt.WRIC_fcts['urlhandle'],
        }

        verbose_messages = {
            True: "\n  Therefore, a nondegenerate solution exists if the FVAC is also satisfied. ("+stge.bilt.WRIC_fcts['urlhandle']+")\n",
            False: "\n  Therefore, a nondegenerate solution is not available ("+stge.bilt.WRIC_fcts['urlhandle']+")\n",
        }
        stge.bilt.WRIC = core_check_condition(name, test, messages, verbose,
                                              verbose_messages, "WRPF", stge)

    def mNrmTrg_find(self):
        """
        Finds value of(normalized) market resources mNrm at which individual consumer
        expects m not to change.

        This will exist if the GICNrm holds.

        https://econ-ark.github.io/BufferStockTheory#UniqueStablePoints

        Parameters
        ----------
        solution : ConsumerSolution
            Solution to this period's problem, which must have attribute cFunc.
        Returns
        -------
            The target value mNrmTrg.
        """

        m_init_guess = self.bilt.mNrmMin + self.E_t.IncNrmNxt
        try:  # Find value where argument is zero
            self.bilt.mNrmTrg = find_zero_newton(
                self.E_t.m_tp1_minus_m_t,
                m_init_guess)
        except:
            self.bilt.mNrmTrg = None

        return self.bilt.mNrmTrg

    def mNrmStE_find(self):
        """
        Finds value of (normalized) market resources m at which consumer
        expects level of market resources M to grow at same rate as the level
        of permanent income P.

        This will exist if the GIC holds.

        https://econ-ark.github.io/BufferStockTheory#UniqueStablePoints

        Parameters
        ----------
        self : ConsumerSolution
            Solution to this period's problem, which must have attribute cFunc.

        Returns
        -------
        self : ConsumerSolution
            Same solution that was passed, but now with attribute mNrmStE.
        """

        # Minimum market resources plus E[next income] is okay starting guess

        m_init_guess = self.bilt.mNrmMin + self.E_t.IncNrmNxt
        try:
            self.bilt.mNrmStE = find_zero_newton(
                self.E_t.permShk_tp1_times_m_tp1_minus_m_t, m_init_guess)
        except:
            self.bilt.mNrmStE = None

        # Add mNrmStE to the solution and return it
        return self.bilt.mNrmStE

# Contents of the PF solver are inherited by a variety of non-PF models
# so ConsPerfForesightSolver incorporates calcs and info useful for
# models in which perfect foresight does not apply

    def finish_setup_of_default_solution_terminal(self):
        """
        Add to `solution_terminal` characteristics which are not automatically
        created as part of the definition of a generic `solution_terminal.`
        """
        # If no solution exists, core.py sets solution_terminal to solution_next
        solution_terminal = self.solution_terminal

        # Natural borrowing constraint: Cannot die in debt
        # Measured after income = tranShk*permShk/permShk received
        if not hasattr(solution_terminal, 'hNrm'):
            _log('warning: hNrm should be set in solution_terminal.')
            _log('assuming solution_terminal.hNrm = 0.')
            solution_terminal.hNrm = 0.0

        # BoroCnstNat might be nonzero if resuming
        solution_terminal.BoroCnstNat = -solution_terminal.hNrm

        # Define BoroCnstArt if not yet defined
        if not hasattr(self.parameters, 'BoroCnstArt'):
            solution_terminal.BoroCnstArt = None
        else:
            solution_terminal.BoroCnstArt = self.parameters.BoroCnstArt

        # pseudo means this will be replaced by richer augmented soln
        solution_terminal.stge_kind = {'iter_status': 'terminal_pseudo'}

        # Always calculate the value function
        solution_terminal.vFuncBool = True

        # Cubic cFunc is problematic with hard kinks where c'' is undefined
        if hasattr(self, 'CubicBool'):
            solution_terminal.CubicBool = self.parameters['CubicBool']
        else:  # default to false (linear)
            solution_terminal.CubicBool = False

        solution_terminal.parameters = self.parameters
        solution_terminal = def_utility(solution_terminal, self.CRRA)
        solution_terminal = def_value_funcs(solution_terminal, self.CRRA)

        return solution_terminal


class ConsPerfForesightSolverEOP(ConsumerSolutionOneStateCRRA):
    """
    Solves a one period perfect foresight
    CRRA utility consumption-saving problem.

    Parameters
    ----------
    solution_next : ConsumerSolution
        The solution to next period's one-period problem.
    DiscFac : float
        Intertemporal discount factor for future utility.
    LivPrb : float
        Survival probability; likelihood of being alive at the beginning of
        the next period.
    CRRA : float
        Coefficient of relative risk aversion.
    Rfree : float
        Risk free interest factor on end-of-period assets.
    PermGroFac : float
        Expected permanent income growth factor at the end of this period.
    BoroCnstArt : float or None
        Artificial borrowing constraint, as a multiple of permanent income.
        Can be None, indicating no artificial constraint.
    MaxKinks : int, optional
        Maximum number of kink points to allow in the consumption function;
        additional points will be thrown out.  Only relevant in infinite
        horizon model with artificial borrowing constraint.
    """
    # CDC 20200426: MaxKinks adds a lot of complexity to little purpose
    # because everything it accomplishes could be done using a finite horizon
    # model (including tests of convergence conditions, which can be invoked
    # manually if a user wants them).

    def __init__(
            self, solution_next, DiscFac=1.0, LivPrb=1.0, CRRA=2.0, Rfree=1.0,
            PermGroFac=1.0, BoroCnstArt=None, MaxKinks=None, **kwds
    ):

        self.soln_futr = soln_futr = solution_next
        self.soln_crnt = ConsumerSolutionOneStateCRRA()

        # Get solver parameters and store for later use
        # omitting things that could cause recursion
        parameters_solver = \
            {k: v for k, v in {**kwds, **locals()}.items()
             if k not in {'self', 'solution_next', 'kwds', 'soln_futr',
                          'bilt_futr', 'soln_crnt', 'bilt'}}

        # 'terminal' solution should replace pseudo_terminal:
        if hasattr(self.soln_futr.bilt, 'stge_kind') and \
                (soln_futr.bilt.stge_kind['iter_status'] == 'terminal_pseudo'):
            self.soln_crnt.bilt = deepcopy(self.soln_futr.bilt)

        # links for docs; urls are used when "fcts" are added
        self.url_doc_for_solver_get()
        self.soln_crnt.bilt.parameters_solver = deepcopy(parameters_solver)

        return

    def url_doc_for_solver_get(self):
        # Generate a url that will locate the documentation
        self.class_name = self.__class__.__name__
        self.soln_crnt.bilt.url_ref = self.url_ref =\
            "https://econ-ark.github.io/BufferStockTheory"
        self.soln_crnt.bilt.urlroot = self.urlroot = \
            self.url_ref+'/#'
        self.soln_crnt.bilt.url_doc = self.url_doc = \
            "https://hark.readthedocs.io/en/latest/search.html?q=" +\
            self.class_name+"&check_keywords=yes&area=default#"

    def cFunc_from_vFunc(self, m):
        #        ρ = self.soln_crnt.pars.CRRA
        vFuncNvrs = self.vFuncNvrs
        vInv = vFuncNvrs(m)
        vInvP = vFuncNvrs.derivative(m)
        cP = self.cFunc.derivative(m)
        cVal = vInv ** (cP / vInvP)
        return cVal

    def make_cFunc_PF(self):
        """
        Makes the (linear) consumption function for this period.  See the
        PerfForesightConsumerType.ipynb notebook for derivations.
        """
        # Reduce cluttered formulae with local aliases
        soln_crnt = self.soln_crnt
        bilt, folw, pars = soln_crnt.bilt, soln_crnt.folw, soln_crnt.pars
        E_t = soln_crnt.E_t

        Rfree, PermGroFac, MPCmin = pars.Rfree, pars.PermGroFac, bilt.MPCmin
        BoroCnstArt, DiscFac, E_t.IncNrmNxt, LivPrb = \
            pars.BoroCnstArt, pars.DiscFac, E_t.IncNrmNxt, pars.LivPrb
        BoroCnstNat = bilt.BoroCnstNat
        u = bilt.u
        u.Nvrs = bilt.u.Nvrs
        u.dc.Nvrs = bilt.u.dc.Nvrs

#        uinv = bilt.uinv
#        uPinv = bilt.uPinv

        folw.PF_IncNrm_tp1 = E_t.IncNrmNxt
        DiscLiv = DiscFac * LivPrb
        CRRA = pars.CRRA
        CRRA_tp1 = folw.vFunc_tp1.CRRA
#        CRRA_tp1 = folw.vFunc_tp1.CRRA

        if BoroCnstArt is None:
            BoroCnstArt = -np.inf

        # Whichever constraint is tighter is the relevant one
        BoroCnst = max(BoroCnstArt, BoroCnstNat)

        # Omit first and last points which define extrapolation below and above
        # the kink points
        folw.mNrm_kinks_tp1 = folw.cFunc_tp1.x_list[:-1][1:]
        folw.cNrm_kinks_tp1 = folw.cFunc_tp1.y_list[:-1][1:]
        folw.vNrm_kinks_tp1 = folw.vFunc_tp1(folw.mNrm_kinks_tp1)

        # Calculate end-of-this-period aNrm vals that would reach those mNrm's
        aNrm_kinks = (folw.mNrm_kinks_tp1 - folw.PF_IncNrm_tp1)*(PermGroFac/Rfree)

        # Obtain c_t from which unconstrained consumers would land on each
        # kink next period by inverting FOC: c_t = (RβΠ)^(-1/ρ) c_tp1
        # This is the endogenous gridpoint (kink point) today
        # corresponding to each next-period kink (each of which corresponds
        # to a finite-horizon solution ending one more period in the future)

        cNrm_kinks = (((Rfree * DiscLiv) ** (-1/CRRA_tp1)) *
                      PermGroFac * folw.cNrm_kinks_tp1)

        vNrm_kinks = (DiscLiv * PermGroFac**(1-CRRA))*folw.vNrm_kinks_tp1
        mNrm_kinks = aNrm_kinks + cNrm_kinks
        vInv_kinks = u.Nvrs(vNrm_kinks)
        vAdd_kinks = mNrm_kinks-mNrm_kinks

        # _v_t(aNrm) is value as of the END of period t
        # _v_t'(aNrmMin) = RβΠ (Γ**(-ρ)) folw.v'(bNrmMin+folw.PF_IncNrmNxt)
        folw.mNrmMin_tp1 = folw.PF_IncNrm_tp1 + BoroCnst * (Rfree/PermGroFac)

        _v_t_at_BoroCnst = \
            (DiscLiv * PermGroFac**(1-CRRA_tp1) *
             folw.vFunc_tp1(folw.mNrmMin_tp1))

        _vP_t_at_BoroCnst = \
            ((Rfree * DiscLiv) * PermGroFac**(-CRRA_tp1) *
             folw.vFunc_tp1.dm(folw.mNrmMin_tp1))

        # h is the 'horizon': h_t(m_t) is the number of periods it will take
        # before you hit the constraint, after which you remain constrained

        # For any c_t where you are unconstrained today, value is discounted
        # sum of values you will receive during periods between now and t+h,
        # and values you will receive afer h
#        vAdd = # Sum of post-constrained value by gridpoint
#            (DiscLiv * PermGroFac**(1-CRRA))*\
#                (bilt.u(folw.cFunc_tp1(mNrm_kinks_tp1) # u at next period cusp
#                        +vAdd_tp1) # v from s

        # cusp is point where current period constraint stops binding
        cNrm_cusp = u.dc.Nvrs(_vP_t_at_BoroCnst)
        vNrm_cusp = bilt.u(cNrm_cusp)+_v_t_at_BoroCnst
        vAdd_cusp = _v_t_at_BoroCnst
        vInv_cusp = u.Nvrs(vNrm_cusp)
        mNrm_cusp = cNrm_cusp + BoroCnst

        # cusp today vs today's implications of future constraints
        if mNrm_cusp >= mNrm_kinks[-1]:  # tighter than the tightest existing
            mNrm_kinks = np.array(mNrm_cusp)  # looser ones are irrelevant
            cNrm_kinks = np.array(cNrm_cusp)
            vNrm_kinks = np.array(vNrm_cusp)
            vInv_kinks = np.array(vInv_cusp)
            vAdd_kinks = np.array(vAdd_cusp)
        else:
            first_reachable = np.where(mNrm_kinks >= mNrm_cusp)[0][-1]
            if first_reachable < mNrm_kinks.size - 1:  # Keep reachable pts
                mNrm_kinks = mNrm_kinks[first_reachable:-1]
                cNrm_kinks = cNrm_kinks[first_reachable:-1]
                vInv_kinks = vInv_kinks[first_reachable:-1]
                vAdd_kinks = vAdd_kinks[first_reachable:-1]
            mNrm_kinks = np.insert(mNrm_kinks, 0, mNrm_cusp)
            cNrm_kinks = np.insert(cNrm_kinks, 0, cNrm_cusp)
            vNrm_kinks = np.insert(vNrm_kinks, 0, vNrm_cusp)
#            vInv_kinks = np.insert(vInv_kinks, 0, vInv_cusp)
#            vAdd_kinks = np.insert(vAdd_kinks, 0, vAdd_cusp)

        vAddGrid = np.append(vAdd_cusp, vAdd_kinks)
        vAddGrid = np.append(vAddGrid, 0.)

        # To guarantee meeting BoroCnst, if mNrm = BoroCnst then cNrm = 0.
        mNrmGrid_unconst = np.append(mNrm_kinks, mNrm_kinks+1)
        cNrmGrid_unconst = np.append(cNrm_kinks, cNrm_kinks+MPCmin)
        aNrmGrid_unconst = mNrmGrid_unconst-cNrmGrid_unconst
        mNrmGrid_tp1_unconst = aNrmGrid_unconst*(Rfree/PermGroFac)+folw.PF_IncNrm_tp1
        vNrmGrid_unconst = u(cNrmGrid_unconst)+(DiscLiv * PermGroFac**(1-CRRA_tp1) *
                                                folw.vFunc_tp1(mNrmGrid_tp1_unconst))
        vInvGrid_unconst = u.Nvrs(vNrmGrid_unconst)
        vInvPGrid_unconst = \
            (((1-CRRA)*vNrmGrid_unconst)**(-1+1/(1-CRRA)))*(cNrmGrid_unconst**(-CRRA))
        c_from_vInvPGrid_unconst = \
            ((vInvPGrid_unconst/(((1-CRRA)*vNrmGrid_unconst)**(-1+1/(1-CRRA)))))**(-1/CRRA)

        mNrmGrid_const = np.array([BoroCnst, mNrm_cusp, mNrm_cusp+1])
        uNrmGrid_const = np.array([float('inf'), u(mNrm_cusp), float('inf')])
        uInvGrid_const = u.Nvrs(uNrmGrid_const)

        def vAddFunc(m, mNrmGrid, vAddGrid):
            mNrmGridPlus = np.append(mNrmGrid, float('inf'))
            vAddGridPlus = np.append(vAddGrid, vAddGrid[-1])
            from collections import Iterable
            if isinstance(m, Iterable):
                from itertools import repeat
                return np.array(list(map(lambda m, mNrmGridPlus, vAddGridPlus:
                                         vAddGridPlus[np.where(m < mNrmGridPlus)[0][0]], m, repeat(mNrmGridPlus), repeat(vAddGridPlus))))
            else:
                return vAddGridPlus[np.where(m < mNrmGridPlus)[0][0]]

#        mPts = np.linspace(mNrmGrid[0],mNrmGrid[-1],10)

        vInvFunc_unconst = \
            LinearInterp(mNrmGrid_unconst, vInvGrid_unconst)

#        from HARK.utilities import plot_funcs
#        plot_funcs(lambda x: np.heaviside(x-BoroCnst,0.5),1,2)
        uInvFunc_const = \
            LinearInterp(mNrmGrid_const, uInvGrid_const)
        vFunc_const = bilt.u(uInvGrid_const)+_v_t_at_BoroCnst
        vFunc_unconst = bilt.u(vInvGrid_unconst)

        def vAddFunc(m, mGrid, vAddGrid):
            return vAddGrid[np.where(m < mGrid)[0][0]]

#        vNrmGrid_const=[BoroCnst,u(mNrmGrid_unconst[0])]

        mNrmGrid = np.append([BoroCnst], mNrmGrid_unconst)
        cNrmGrid = np.append(0., cNrmGrid_unconst)
        vInvGrid = np.append(0., vInvGrid_unconst)
#        vInvPGrid = np.append(float('inf'), vInvPGrid_unconst)
#        vInvGrid = np.insert(vInvGrid, 0, -1)

        # Above last kink point, use PF solution
#        mNrmGrid = np.append(mNrmGrid, mNrmGrid[-1]+1)
#        cNrmGrid = np.append(cNrmGrid, cNrmGrid[-1]+MPCmin)
#        aNrmGrid = mNrmGrid - cNrmGrid
#        bNrmGrid_tp1 = aNrmGrid*(Rfree/PermGroFac)
#        mNrmGrid_tp1 = bNrmGrid_tp1+folw.PF_IncNrm_tp1
#        vNrmGrid = u(cNrmGrid)+(DiscLiv * PermGroFac**(1-CRRA_tp1) *
#             folw.vFunc_tp1(mNrmGrid_tp1))
#        vInvGrid = (vNrmGrid*(1-CRRA))**(1/(1-CRRA))

#        vInvGrid = np.append(vInvGrid, vInvGrid[-1]+MPCmin**(-CRRA/(1.0-CRRA)))

        # To guarantee meeting BoroCnst, if mNrm = BoroCnst then cNrm = 0.
        mNrmGrid = np.append([BoroCnst], mNrm_kinks)
        cNrmGrid = np.append(0., cNrm_kinks)

        # Above last kink point, use PF solution
        mNrmGrid = np.append(mNrmGrid, mNrmGrid[-1]+1)
        cNrmGrid = np.append(cNrmGrid, cNrmGrid[-1]+MPCmin)

        self.cFunc = self.soln_crnt.cFunc = bilt.cFunc = \
            LinearInterp(mNrmGrid, cNrmGrid)

#        vInvFunc_unconst = self.vFuncNvrs = \
#            LinearInterp(mNrmGrid,vInvGrid)

        # self.vNvrsFunc.derivative(m)
        # (vNvrsFunc.derivative(/(((1-CRRA)*vInvGrid_unconst)**(-1+1/(1-CRRA))))

#        cc = self.cFunc_from_vFunc(2.0)
#        cFromvP=uPinv(vP_Grid)
#        cFuncFromvNvrsFunc = LinearInterp(mNrmGrid,cFromvP)
#        from HARK.utilities import plot_funcs
#        plot_funcs([self.cFunc,cFuncFromvNvrsFunc],0,2)

#        print('hi')
#        PF_t_v_tp1_last = (DiscLiv*(PermGroFac ** (1-CRRA_tp1)))*\
#            np.float(folw.vFunc_tp1((Rfree/PermGroFac)*aNrmGrid[-1]+E_t.IncNrmNxt))
#        PF_t_vNvrs_tp1_Grid_2 = \
#            np.append(PF_t_vNvrs_tp1_Grid,PF_t_v_tp1_last)

        # vNvrsGrid = bilt.uinv(bilt.u(cNrmGrid)+ folw.u_tp1(PF_t_vNvrs_tp1_Grid))

        # If the mNrm that would unconstrainedly yield next period's bottom pt
#        if BoroCnst > mNrmGrid_pts[0]: # is prohibited by BoroCnst
#            satisfies_BoroCnst = np.where(
#                mNrmGrid_unconst - BoroCnst < cNrm_from_aNrmMin) # True if OK

        # Amount of m in excess of minimum possible m
#        mNrmXtraGrid = mNrmGrid_pts - BoroCnst

        # We think of the stage at which income has been realized
        # as prior to the start of the period when the problem is solved.
        # You "enter" the period with normalized market resources mNrm
        # If this is starting period of life, we want problem to be defined all
        # the way down to the point where c would be forced to be zero
        # That requires us to find the min aNrm with which the period can end
#        cNrmMin = 0. # You cannot spend anything and still satisfy constraint

        # Find first kink point in existing grid
#        kink_min = np.where(mNrmXtraGrid <= cNrmGrid_pts)[0][-1]
#        kink_min = np.where(aNrmGrid_pts <= BoroCnst)[0][-1]

        # Now calculate the minimum mNrm that will be possible for a consumer
        # who lived in the prior period and in that period satisfied the
        # relevant borrowing constraint
#        _bNrmMin = aNrmMin*(Rfree/PermGroFac)
#        mNrmMin = _bNrmMin + BoroCnst
#        mNrmMin_with_income = mNrmMin + folw.PF_IncNrmNxt
 #       if c_at_aNrmMin > aNrmMin+folw.PF_IncNrmNxt-BoroCnst:
        # The u' from ending this period with aNrm = BoroCnst exceeds
        # u' from the last penny of spending, so the consumer
        # at

#            mNrmGrid_pts = np.insert(mNrmGrid_pts,kink_min,mNrmMin_with_income)
#            cNrmGrid_pts = np.insert(cNrmGrid_pts,kink_min,mNrmMin_with_income)

        # Last index where constraint binds (in current period)
#        kink_min = np.where(mNrmXtraGrid <= cNrmGrid)[0][-1]
#        mNrmGrid_pts = np.insert(mNrmGrid_pts,kink_min,mNrmMin)
#        cNrmGrid_pts = np.insert(cNrmGrid_pts,kink_min,cNrmMin)

        # The minimum m if you were at the binding borrowing constraint

        # at the end of the last period (assumes prior period's )
#         mNrmMin_BoroCnstLast = BoroCnst*(Rfree/PermGroFac)

# #        mNrmGrid_pts = np.insert(mNrmGrid,kink_min,bNrmMin+PF_IncNrmNow)
# #        cNrmGrid_pts = np.insert(cNrmGrid,kink_min,bNrmMin+PF_IncNrmNow)
#         kink_max = np.where(mNrmXtraGrid >= cNrmGrid)[0][-1]

#         # Below binding point, c is maximum allowed, which is attained by line
#         # from [BoroCnst,0.] to [mNrmGrid[cusp],mNrmGrid[cusp]]
#         cNrmGrid_pts = np.insert(cNrmGrid,kink_min,)

#         mNrmGrid_pts = np.insert(mNrmGrid,kink_min-1,E_t.IncNrmNxt)
#         cNrmGrid_pts = np.insert(cNrmGrid,kink_min-1,E_t.IncNrmNxt-BoroCnst)

#        mNrmGrid_pts = np.append(mNrmGrid_pts,mNrmGrid_pts[-1]+1.)
#        cNrmGrid_pts = np.append(cNrmGrid_pts,cNrmGrid_pts[-1]+MPCmin)


#         mNrmGrid = np.insert(mNrmGrid,0,mNrmMin)
#         cNrmGrid = np.insert(cNrmGrid,0,0.)


#         if BoroCnstArt+E_t.IncNrmNxt > mNrmGrid[0]:
#             mNrmGrid

#         mNrmGrid = np.append(mNrmGrid,mNrmGrid[-1]+1.0)
#         cNrmGrid = np.append(cNrmGrid,cNrmGrid[-1]+MPCmin)


#         # Add the point corresponding to
#         mNrmGrid = np.unique(np.insert(mNrmGrid,0,E_t.IncNrmNxt-BoroCnstArt))
#         cNrmGrid = np.unique(np.insert(cNrmGrid,0,E_t.IncNrmNxt-BoroCnstArt))


# #        vNvrs_tp1 = (DiscLiv * LivPrb) * folw.vFunc_tp1(mNrmGrid_tp1)
# #        PF_t_vNvrs_tp1_Grid = folw.uinv_tp1(DiscLiv) * \
# #            folw.vFuncNvrs_tp1.y_list
#         # Beginning-of-period-tp1 marginal value vec is vP_tp1
# #        vP_tp1 = folw.uP_tp1(cNrmGrid_tp1)
#         # Corresponding end-of-period-t marginal value is _vP_t
# #        _vP_t = ((DiscLiv * Rfree) * (PermGroFac**(-CRRA_tp1)))*vP_tp1
# #        _vP_t =
#         # Endogenous gridpoints method
#  #       cNrmGrid = bilt.uPinv(_vP_t)    # EGM step 1: u' inverse yields c
#         mNrmGrid = aNrmGrid + cNrmGrid  # EGM step 2: DBC inverted

#         cNrmGrid = np.unique(np.insert(cNrmGrid,0,E_t.IncNrmNxt-BoroCnstArt))

#         # Add additional point to the list of gridpoints for extrapolation,
#         # using this period's new value of the lower bound of the MPC, which
#         # defines the PF unconstrained problem through the end of the horizon
# #        mNrmGrid_interp_pts = np.append(mNrmGrid, mNrmGrid[-1] + 1.0)
# #        cNrmGrid_interp_pts = np.append(cNrmGrid, cNrmGrid[-1] + MPCmin)
#         # If artificial borrowing constraint binds, combine constrained and
#         # unconstrained consumption functions.

#         # The problem is well-defined down to BoroCnstArt even if in
#         # principle from t you could not get to any m_tp1 < E_t.IncNrmNxt
#         # because nothing prevents you from starting tp1 with m \geq BoroCnstArt
#  #       if BoroCnstArt < mNrmGrid[0] - E_t.IncNrmNxt:
#  #           mNrmGrid_interp_pts = np.append([BoroCnstArt], mNrmGrid_interp_pts)
#  #           cNrmGrid_interp_pts = np.append([BoroCnstArt], cNrmGrid_interp_pts)
# #        else: # BoroCnstArt is irrelevant if BoroCnstNat is tighter
#             # cNrmGridCnst defines points where cnst would bind for each m gpt
# #        cNrmGridCnst = mNrmGrid_interp_pts - BoroCnstArt
#         mXtraGrid = mNrmGrid - BoroCnstArt # m in excess of minimum m
# #        idx_binding =   # c > possible
#         # highest m where cnst binds
#         idx_binding_last = np.where(mNrmXtraGrid <= cNrmGrid)[0][-1]
#         if idx_binding_last < (mNrmGrid.size - 1):
#             print('hi')
#             # # If not the *very last* index, find the the critical level
#             # # of mNrmGrid where artificial cnst begins to bind.
#             # d0 = cNrmGrid[idx] - cNrmGridCnst[idx]
#             # d1 = cNrmGridCnst[idx + 1] - cNrmGrid[idx + 1]
#             # m0 = mNrmGrid[idx]
#             # m1 = mNrmGrid[idx + 1]
#             # alpha = d0 / (d0 + d1)
#             # mCrit = m0 + alpha * (m1 - m0)
#             # # Adjust grids of mNrmGrid and cNrmGrid to account for constraint.
#             # cCrit = mCrit - BoroCnstArt
#             # mNrmGrid = np.concatenate(([BoroCnstArt, mCrit], mNrmGrid[(idx + 1):]))
#             # cNrmGrid = np.concatenate(([0.0, cCrit], cNrmGrid[(idx + 1):]))
#             # aNrmGrid = mNrmGrid-cNrmGrid
#         else:
#             # If it *is* the last index, then there are only three points
#             # that characterize the c function: the artificial borrowing
#             # constraint, the constraint kink, and the extrapolation point
#             mAbve= 1.0 # (cNrmGrid[-1] - cNrmGridCnst[-1]) / (1.0 - MPCmin)
#             mNrm_max_bindpoint = mNrmGrid[idx_binding_last]
#             cNrm_max_bindpoint = cNrmGrid[idx_binding_last]
# #                mCrit = mNrmGrid[-1] + mXtra
# #                cCrit = mCrit - BoroCnstArt
#             mNrmGrid_Xtra = np.array(
#                 [BoroCnstArt, mNrm_max_bindpoint, mNrm_max_bindpoint + 1])
#             cNrmGrid_Xtra = np.array(
#                 [0.0, cNrm_max_bindpoint, cNrm_max_bindpoint + MPCmin])
#             aNrmGrid_Xtra = mNrmGrid_Xtra- cNrmGrid_Xtra
#             # If mNrmGrid, cNrmGrid grids have become too large, throw out last
#             # kink point, being sure to adjust the extrapolation.

#         if mNrmGrid.size > MaxKinks:
#             mNrmGrid = np.concatenate((mNrmGrid[:-2], [cNrmGrid[-3] + 1.0]))
#             cNrmGrid = np.concatenate((cNrmGrid[:-2], [cNrmGrid[-3] + MPCmin]))
#             aNrmGrid = mNrmGrid - cNrmGrid

        # Consumption function is a linear interpolation between kink pts
#        self.cFunc = self.soln_crnt.cFunc = bilt.cFunc = \
#            LinearInterp(mNrmGrid_pts, cNrmGrid_pts)


#        PF_t_v_tp1_last = (DiscLiv*(PermGroFac ** (1-CRRA_tp1)))*\
#            np.float(folw.vFunc_tp1((Rfree/PermGroFac)*aNrmGrid[-1]+E_t.IncNrmNxt))
#        PF_t_vNvrs_tp1_Grid_2 = \
#            np.append(PF_t_vNvrs_tp1_Grid,PF_t_v_tp1_last)

        # vNvrsGrid = bilt.uinv(bilt.u(cNrmGrid)+ folw.u_tp1(PF_t_vNvrs_tp1_Grid))

        # # Calculate the upper bound of the MPC as the slope of bottom segment
        # # In practice, this is always 1.  Code is here for clarity
        # bilt.MPCmax = ((cNrmGrid_Xtra[1] - cNrmGrid_Xtra[0])/
        #                (mNrmGrid_Xtra[1] - mNrmGrid_Xtra[0]))

        # # Lower bound of mNrm is lowest gridpoint -- usually 0
        # bilt.mNrmMin = mNrmGrid_Xtra[0]

        # # Add the calculated grids to self.bilt
        # bilt.aNrmGrid = aNrmGrid_Xtra
        # bilt._vP_t = _vP_t
        # bilt.cNrmGrid = cNrmGrid_Xtra
        # bilt.mNrmGrid = mNrmGrid_Xtra

        # Add approximation to v and vP
#        breakpoint()
#        bilt.vNvrs = self.soln_crnt.uinv(_vP_t)

#    def build_infhor_facts_from_params_ConsPerfForesightSolver(self):

# 20210618: TODO: CDC: Find a way to isolate this stuff so it does not clutter


    def build_infhor_facts_from_params(self):
        """
            Adds to the solution extensive information and references about
            its nature and elements.

            Parameters
            ----------
            solution: ConsumerSolution
                Solution that already has minimal requirements (vPfunc, cFunc)

            Returns
            -------
            solution : ConsumerSolution
                Same solution that was provided, augmented with facts
        """

        # Using local variables makes formulae more readable
        soln_crnt = self.soln_crnt  # current
        bilt = self.soln_crnt.bilt  # built
        folw = self.soln_crnt.folw  # following stage
        pars = self.soln_crnt.pars  # parameters

        E_t = self.soln_crnt.E_t

        urlroot = bilt.urlroot
        pars.DiscLiv = pars.DiscFac * pars.LivPrb
        givens = {**folw.__dict__, **pars.__dict__}

        APF_fcts = {
            'about': 'Absolute Patience Factor'
        }
        py___code = '((Rfree * DiscLiv) ** (1.0 / CRRA))'
        bilt.APF = APF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        APF_fcts.update({'latexexpr': r'\APF'})
        APF_fcts.update({'_unicode_': r'Þ'})
        APF_fcts.update({'urlhandle': urlroot+'APF'})
        APF_fcts.update({'py___code': py___code})
        APF_fcts.update({'value_now': APF})
        bilt.APF_fcts = APF_fcts

        AIC_fcts = {
            'about': 'Absolute Impatience Condition'
        }
        AIC_fcts.update({'latexexpr': r'\AIC'})
        AIC_fcts.update({'urlhandle': urlroot+'AIC'})
        AIC_fcts.update({'py___code': 'test: APF < 1'})
        bilt.AIC_fcts = AIC_fcts

        RPF_fcts = {
            'about': 'Return Patience Factor'
        }
        py___code = 'APF / Rfree'
        bilt.RPF = RPF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        RPF_fcts.update({'latexexpr': r'\RPF'})
        RPF_fcts.update({'_unicode_': r'Þ_R'})
        RPF_fcts.update({'urlhandle': urlroot+'RPF'})
        RPF_fcts.update({'py___code': py___code})
        RPF_fcts.update({'value_now': RPF})
        bilt.RPF_fcts = RPF_fcts

        RIC_fcts = {
            'about': 'Growth Impatience Condition'
        }
        RIC_fcts.update({'latexexpr': r'\RIC'})
        RIC_fcts.update({'urlhandle': urlroot+'RIC'})
        RIC_fcts.update({'py___code': 'test: RPF < 1'})
        bilt.RIC_fcts = RIC_fcts

        GPFRaw_fcts = {
            'about': 'Growth Patience Factor'
        }
        py___code = 'APF / PermGroFac'
        bilt.GPFRaw = GPFRaw = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        GPFRaw_fcts.update({'latexexpr': '\GPFRaw'})
        GPFRaw_fcts.update({'_unicode_': r'Þ_Γ'})
        GPFRaw_fcts.update({'urlhandle': urlroot+'GPFRaw'})
        GPFRaw_fcts.update({'py___code': py___code})
        GPFRaw_fcts.update({'value_now': GPFRaw})
        bilt.GPFRaw_fcts = GPFRaw_fcts

        GICRaw_fcts = {
            'about': 'Growth Impatience Condition'
        }
        GICRaw_fcts.update({'latexexpr': r'\GICRaw'})
        GICRaw_fcts.update({'urlhandle': urlroot+'GICRaw'})
        GICRaw_fcts.update({'py___code': 'test: GPFRaw < 1'})
        bilt.GICRaw_fcts = GICRaw_fcts

        GPFLiv_fcts = {
            'about': 'Mortality-Adjusted Growth Patience Factor'
        }
        py___code = 'APF * LivPrb / PermGroFac'
        bilt.GPFLiv = GPFLiv = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        GPFLiv_fcts.update({'latexexpr': '\GPFLiv'})
        GPFLiv_fcts.update({'urlhandle': urlroot+'GPFLiv'})
        GPFLiv_fcts.update({'py___code': py___code})
        GPFLiv_fcts.update({'value_now': GPFLiv})
        bilt.GPFLiv_fcts = GPFLiv_fcts

        GICLiv_fcts = {
            'about': 'Growth Impatience Condition'
        }
        GICLiv_fcts.update({'latexexpr': r'\GICLiv'})
        GICLiv_fcts.update({'urlhandle': urlroot+'GICLiv'})
        GICLiv_fcts.update({'py___code': 'test: GPFLiv < 1'})
        bilt.GICLiv_fcts = GICLiv_fcts

        RNrm_PF_fcts = {
            'about': 'Growth-Normalized PF Return Factor'
        }
        py___code = 'Rfree/PermGroFac'
        E_t.RNrm_PF = RNrm_PF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        RNrm_PF_fcts.update({'latexexpr': r'\PFRNrm'})
        RNrm_PF_fcts.update({'_unicode_': r'R/Γ'})
        RNrm_PF_fcts.update({'py___code': py___code})
        RNrm_PF_fcts.update({'value_now': RNrm_PF})
        E_t.RNrm_PF_fcts = RNrm_PF_fcts

        Inv_RNrm_PF_fcts = {
            'about': 'Inv of Growth-Normalized PF Return Factor'
        }
        py___code = '1 / RNrm_PF'
        E_t.Inv_RNrm_PF = Inv_RNrm_PF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        Inv_RNrm_PF_fcts.update({'latexexpr': r'\InvPFRNrm'})
        Inv_RNrm_PF_fcts.update({'_unicode_': r'Γ/R'})
        Inv_RNrm_PF_fcts.update({'py___code': py___code})
        Inv_RNrm_PF_fcts.update({'value_now': Inv_RNrm_PF})
        E_t.Inv_RNrm_PF_fcts = \
            Inv_RNrm_PF_fcts

        FHWF_fcts = {
            'about': 'Finite Human Wealth Factor'
        }
        py___code = 'PermGroFac / Rfree'
        bilt.FHWF = FHWF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        FHWF_fcts.update({'latexexpr': r'\FHWF'})
        FHWF_fcts.update({'_unicode_': r'R/Γ'})
        FHWF_fcts.update({'urlhandle': urlroot+'FHWF'})
        FHWF_fcts.update({'py___code': py___code})
        FHWF_fcts.update({'value_now': FHWF})
        bilt.FHWF_fcts = \
            FHWF_fcts

        FHWC_fcts = {
            'about': 'Finite Human Wealth Condition'
        }
        FHWC_fcts.update({'latexexpr': r'\FHWC'})
        FHWC_fcts.update({'urlhandle': urlroot+'FHWC'})
        FHWC_fcts.update({'py___code': 'test: FHWF < 1'})
        bilt.FHWC_fcts = FHWC_fcts

        hNrmInf_fcts = {
            'about': 'Human wealth for inf hor'
        }
        py___code = '1/(1-FHWF) if (FHWF < 1) else float("inf")'
        bilt.hNrmInf = hNrmInf = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        hNrmInf_fcts = dict({'latexexpr': '1/(1-\FHWF)'})
        hNrmInf_fcts.update({'value_now': hNrmInf})
        hNrmInf_fcts.update({'py___code': py___code})
        bilt.hNrmInf_fcts = hNrmInf_fcts

        DiscGPFRawCusp_fcts = {
            'about': 'DiscFac s.t. GPFRaw = 1'
        }
        py___code = '( PermGroFac                       ** CRRA)/(Rfree)'
        bilt.DiscGPFRawCusp = DiscGPFRawCusp = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        DiscGPFRawCusp_fcts.update({'latexexpr': '\PermGroFac^{\CRRA}/\Rfree'})
        DiscGPFRawCusp_fcts.update({'value_now': DiscGPFRawCusp})
        DiscGPFRawCusp_fcts.update({'py___code': py___code})
        bilt.DiscGPFRawCusp_fcts = \
            DiscGPFRawCusp_fcts

        DiscGPFLivCusp_fcts = {
            'about': 'DiscFac s.t. GPFLiv = 1'
        }
        py___code = '( PermGroFac                       ** CRRA)/(Rfree*LivPrb)'
        bilt.DiscGPFLivCusp = DiscGPFLivCusp = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        DiscGPFLivCusp_fcts.update({'latexexpr': '\PermGroFac^{\CRRA}/(\Rfree\LivPrb)'})
        DiscGPFLivCusp_fcts.update({'value_now': DiscGPFLivCusp})
        DiscGPFLivCusp_fcts.update({'py___code': py___code})
        bilt.DiscGPFLivCusp_fcts = DiscGPFLivCusp_fcts

        FVAF_fcts = {  # overwritten by version with uncertainty
            'about': 'Finite Value of Autarky Factor'
        }
        py___code = 'LivPrb * DiscLiv'
        bilt.FVAF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        FVAF_fcts.update({'latexexpr': r'\FVAFPF'})
        FVAF_fcts.update({'urlhandle': urlroot+'FVAFPF'})
        FVAF_fcts.update({'py___code': py___code})
        bilt.FVAF_fcts = FVAF_fcts

        FVAC_fcts = {  # overwritten by version with uncertainty
            'about': 'Finite Value of Autarky Condition - Perfect Foresight'
        }
        FVAC_fcts.update({'latexexpr': r'\FVACPF'})
        FVAC_fcts.update({'urlhandle': urlroot+'FVACPF'})
        FVAC_fcts.update({'py___code': 'test: FVAFPF < 1'})
        bilt.FVAC_fcts = FVAC_fcts

        E_t.IncNrmNxt_fcts = {  # Overwritten by version with uncertainty
            'about': 'Expected income next period'
        }
        py___code = '1.0'
#        soln_crnt.E_t.IncNrmNxt = \
        E_t.IncNrmNxt = E_t.IncNrmNxt = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
#        E_t.IncNrmNxt_fcts.update({'latexexpr': r'ExIncNrmNxt'})
#        E_t.IncNrmNxt_fcts.update({'_unicode_': r'R/Γ'})
#        E_t.IncNrmNxt_fcts.update({'urlhandle': urlroot+'ExIncNrmNxt'})
        E_t.IncNrmNxt_fcts.update({'py___code': py___code})
        E_t.IncNrmNxt_fcts.update({'value_now': E_t.IncNrmNxt})
        # soln_crnt.fcts.update({'E_t.IncNrmNxt': E_t.IncNrmNxt_fcts})
#        soln_crnt.E_t.IncNrmNxt_fcts =
        soln_crnt.E_t.IncNrmNxt_fcts = E_t.IncNrmNxt_fcts

        RNrm_PF_fcts = {
            'about': 'Expected Growth-Normalized Return'
        }
        py___code = 'Rfree / PermGroFac'
        E_t.RNrm_PF = RNrm_PF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        RNrm_PF_fcts.update({'latexexpr': r'\PFRNrm'})
        RNrm_PF_fcts.update({'_unicode_': r'R/Γ'})
        RNrm_PF_fcts.update({'urlhandle': urlroot+'PFRNrm'})
        RNrm_PF_fcts.update({'py___code': py___code})
        RNrm_PF_fcts.update({'value_now': RNrm_PF})
        E_t.RNrm_PF_fcts = RNrm_PF_fcts

        RNrm_PF_fcts = {
            'about': 'Expected Growth-Normalized Return'
        }
        py___code = 'Rfree / PermGroFac'
        E_t.RNrm_PF = RNrm_PF = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        RNrm_PF_fcts.update({'latexexpr': r'\PFRNrm'})
        RNrm_PF_fcts.update({'_unicode_': r'R/Γ'})
        RNrm_PF_fcts.update({'urlhandle': urlroot+'PFRNrm'})
        RNrm_PF_fcts.update({'py___code': py___code})
        RNrm_PF_fcts.update({'value_now': RNrm_PF})
        E_t.RNrm_PF_fcts = RNrm_PF_fcts

        DiscLiv_fcts = {
            'about': 'Mortality-Inclusive Discounting'
        }
        py___code = 'DiscFac * LivPrb'
        bilt.DiscLiv = DiscLiv = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        DiscLiv_fcts.update({'latexexpr': r'\PFRNrm'})
        DiscLiv_fcts.update({'_unicode_': r'R/Γ'})
        DiscLiv_fcts.update({'urlhandle': urlroot+'PFRNrm'})
        DiscLiv_fcts.update({'py___code': py___code})
        DiscLiv_fcts.update({'value_now': DiscLiv})
        bilt.DiscLiv_fcts = DiscLiv_fcts

    def build_recursive_facts(self):

        soln_crnt = self.soln_crnt
        bilt = soln_crnt.bilt
        folw = soln_crnt.folw
        pars = soln_crnt.pars
        E_t = soln_crnt.E_t

        givens = {**folw.__dict__, **pars.__dict__}
        urlroot = bilt.urlroot
        pars.DiscLiv = pars.DiscFac * pars.LivPrb

        hNrm_fcts = {
            'about': 'Human Wealth '
        }
        py___code = '((PermGroFac / Rfree) * (1.0 + hNrm_tp1))'
        if soln_crnt.stge_kind['iter_status'] == 'terminal_pseudo':  # kludge:
            soln_crnt.hNrm_tp1 = -1.0  # causes hNrm = 0 for final period
        bilt.hNrm = hNrm = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        hNrm_fcts.update({'latexexpr': r'\hNrm'})
        hNrm_fcts.update({'_unicode_': r'R/Γ'})
        hNrm_fcts.update({'urlhandle': urlroot+'hNrm'})
        hNrm_fcts.update({'py___code': py___code})
        hNrm_fcts.update({'value_now': hNrm})
        bilt.hNrm_fcts = hNrm_fcts

        BoroCnstNat_fcts = {
            'about': 'Natural Borrowing Constraint'
        }
        py___code = '(mNrmMin_tp1 - tranShkMin)*(PermGroFac/Rfree)*permShkMin'
        if soln_crnt.stge_kind['iter_status'] == 'terminal_pseudo':  # kludge
            py___code = 'hNrm'  # Presumably zero
        bilt.BoroCnstNat = BoroCnstNat = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        BoroCnstNat_fcts.update({'latexexpr': r'\BoroCnstNat'})
        BoroCnstNat_fcts.update({'_unicode_': r''})
        BoroCnstNat_fcts.update({'urlhandle': urlroot+'BoroCnstNat'})
        BoroCnstNat_fcts.update({'py___code': py___code})
        BoroCnstNat_fcts.update({'value_now': BoroCnstNat})
        bilt.BoroCnstNat_fcts = BoroCnstNat_fcts

        BoroCnst_fcts = {
            'about': 'Effective Borrowing Constraint'
        }
        py___code = 'BoroCnstNat if (BoroCnstArt == None) else (BoroCnstArt if BoroCnstNat < BoroCnstArt else BoroCnstNat)'
        bilt.BoroCnst = BoroCnst = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        BoroCnst_fcts.update({'latexexpr': r'\BoroCnst'})
        BoroCnst_fcts.update({'_unicode_': r''})
        BoroCnst_fcts.update({'urlhandle': urlroot+'BoroCnst'})
        BoroCnst_fcts.update({'py___code': py___code})
        BoroCnst_fcts.update({'value_now': BoroCnst})
        bilt.BoroCnst_fcts = BoroCnst_fcts

        # MPCmax is not a meaningful object in the PF model so is not created there
        # so create it here
        MPCmax_fcts = {
            'about': 'Maximal MPC in current period as m -> mNrmMin'
        }
        py___code = '1.0 / (1.0 + (RPF / MPCmax_tp1))'
        if soln_crnt.stge_kind['iter_status'] == 'terminal_pseudo':  # kludge:
            soln_crnt.MPCmax_tp1 = float('inf')  # causes MPCmax = 1 for final period
        bilt.MPCmax = MPCmax = eval(
            py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        MPCmax_fcts.update({'latexexpr': r''})
        MPCmax_fcts.update({'urlhandle': urlroot+'MPCmax'})
        MPCmax_fcts.update({'py___code': py___code})
        MPCmax_fcts.update({'value_now': MPCmax})
        bilt.MPCmax_fcts = MPCmax_fcts

        mNrmMin_fcts = {
            'about': 'Min m is the max you can borrow'
        }
        py___code = 'BoroCnst'
        bilt.mNrmMin =  \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        mNrmMin_fcts.update({'latexexpr': r'\mNrmMin'})
        mNrmMin_fcts.update({'py___code': py___code})
        bilt.mNrmMin_fcts = mNrmMin_fcts

        MPCmin_fcts = {
            'about': 'Minimal MPC in current period as m -> infty'
        }
        py___code = '1.0 / (1.0 + (RPF /MPCmin_tp1))'
        if soln_crnt.stge_kind['iter_status'] == 'terminal_pseudo':  # kludge:
            #        if soln_crnt.bilt.stge_kind['iter_status'] == 'terminal_pseudo':  # kludge:
            bilt.MPCmin_tp1 = float('inf')  # causes MPCmin = 1 for final period
        bilt.MPCmin = MPCmin = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        MPCmin_fcts.update({'latexexpr': r''})
        MPCmin_fcts.update({'urlhandle': urlroot+'MPCmin'})
        MPCmin_fcts.update({'py___code': py___code})
        MPCmin_fcts.update({'value_now': MPCmin})
        bilt.MPCmin_fcts = MPCmin_fcts

        MPCmax_fcts = {
            'about': 'Maximal MPC in current period as m -> mNrmMin'
        }
        py___code = '1.0 / (1.0 + (RPF / MPCmax_tp1))'
        if soln_crnt.stge_kind['iter_status'] == 'terminal_pseudo':  # kludge:
            bilt.MPCmax_tp1 = float('inf')  # causes MPCmax = 1 for final period
        bilt.MPCmax = MPCmax = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        MPCmax_fcts.update({'latexexpr': r''})
        MPCmax_fcts.update({'urlhandle': urlroot+'MPCmax'})
        MPCmax_fcts.update({'py___code': py___code})
        MPCmax_fcts.update({'value_now': MPCmax})
        bilt.MPCmax_fcts = MPCmax_fcts

        cFuncLimitIntercept_fcts = {
            'about': 'Vertical intercept of perfect foresight consumption function'}
        py___code = 'MPCmin * hNrm'
#        soln_crnt.cFuncLimitIntercept = \
        bilt.cFuncLimitIntercept = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        cFuncLimitIntercept_fcts.update({'py___code': py___code})
        cFuncLimitIntercept_fcts.update({'latexexpr': '\MPC \hNrm'})
#        cFuncLimitIntercept_fcts.update({'urlhandle': ''})
#        cFuncLimitIntercept_fcts.update({'value_now': cFuncLimitIntercept})
        soln_crnt.bilt.cFuncLimitIntercept_fcts = cFuncLimitIntercept_fcts

        cFuncLimitSlope_fcts = {
            'about': 'Slope of limiting consumption function'}
        py___code = 'MPCmin'
        cFuncLimitSlope_fcts.update({'py___code': 'MPCmin'})
        bilt.cFuncLimitSlope = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        cFuncLimitSlope_fcts.update({'py___code': py___code})
        cFuncLimitSlope_fcts = dict({'latexexpr': '\MPCmin'})
        cFuncLimitSlope_fcts.update({'urlhandle': '\MPC'})
#        cFuncLimitSlope_fcts.update({'value_now': cFuncLimitSlope})
        soln_crnt.bilt.cFuncLimitSlope_fcts = cFuncLimitSlope_fcts

        # That's the end of things that are identical for PF and non-PF models

        return soln_crnt

    def solve_prepared_stage(self):  # inside ConsPerfForesightSolver
        """
        Solve the one-period/stage consumption-saving problem.

        Parameters
        ----------
        None (all should be in self)

        Returns
        -------
        solution : ConsumerSolution
            The solution to this period/stage's problem.
        """
        soln_futr = self.soln_futr
        soln_crnt = self.soln_crnt
        CRRA = soln_crnt.pars.CRRA

        if soln_futr.bilt.stge_kind['iter_status'] == 'finished':
            breakpoint()
            # Should not have gotten here
            # because core.py tests whether solution_last is 'finished'

        if soln_futr.bilt.stge_kind['iter_status'] == 'terminal_pseudo':
            # bare-bones default terminal solution does not have all the facts
            # we want, because it is multipurpose (for any u func) so add them
            soln_futr.bilt = def_utility(soln_crnt, CRRA)
            self.build_infhor_facts_from_params()
            soln_futr = soln_crnt = def_value_funcs(soln_crnt, CRRA)
            # Now that they've been added, it's good to go for iteration
            soln_crnt.bilt.stge_kind['iter_status'] = 'iterator'
            soln_crnt.stge_kind = soln_crnt.bilt.stge_kind
            self.soln_crnt.vPfunc = self.soln_crnt.bilt.vPfunc  # Need for distance
            self.soln_crnt.cFunc = self.soln_crnt.bilt.cFunc  # Need for distance
            if hasattr(self.soln_crnt.bilt, 'IncShkDstn'):
                self.soln_crnt.IncShkDstn = self.soln_crnt.bilt.IncShkDstn

            return soln_crnt  # if pseudo_terminal = True, enhanced replaces original

        CRRA = self.soln_crnt.pars.CRRA
        self.soln_crnt = def_utility(soln_crnt, CRRA)
        self.build_infhor_facts_from_params()
        self.build_recursive_facts()
        self.make_cFunc_PF()
        soln_crnt = def_value_funcs(soln_crnt, CRRA)

        return soln_crnt

    solve = solve_prepared_stage

    def solver_prep_solution_for_an_iteration(self):  # self: solver for stage
        """
        Prepare the current stage for processing by the one-stage solver.
        """

        soln_crnt = self.soln_crnt
        soln_futr = self.soln_futr

        bilt, pars = soln_crnt.bilt, soln_crnt.pars

        # Create current pars
        for key in (k for k in bilt.parameters_solver
                    if k not in {'', ''}):
            setattr(pars, key, bilt.parameters_solver[key])

        # Organizing principle: folw should have a deepcopy of everything
        # needed to re-solve crnt problem; and everything needed to construct
        # the "fcts" about current stage of the problem, so that the stge could
        # be deepcopied as a standalone object and solved without soln_futr
        # or soln_crnt

        folw = soln_crnt.folw = Successor()

        # Catch degenerate case of zero-variance income distributions
        if hasattr(pars, "tranShkVals") and hasattr(pars, "permShkVals"):
            if ((pars.tranShkMin == 1.0) and (pars.permShkMin == 1.0)):
                soln_crnt.E_t.Inv_permShk = 1.0
                soln_crnt.E_t.uInv_permShk = 1.0
        else:
            pars.tranShkMin = pars.permShkMin = 1.0

        # Nothing needs to be done for terminal_pseudo
        if hasattr(bilt, 'stge_kind'):
            if 'iter_status' in bilt.stge_kind:
                if (bilt.stge_kind['iter_status'] == 'terminal_pseudo'):
                    # No work needed in terminal period, which replaces itself
                    return

        # Create folw
        for key in (k for k in bilt.recursive
                    if k not in
                    {'solution_next', 'bilt', 'stge_kind', 'folw'}):
            if hasattr(soln_futr.bilt, key):
                setattr(folw, key+'_tp1',
                        soln_futr.bilt.__dict__[key])

        # # Add futr parameters to folw
        # for key in (k for k in soln_futr.pars.__dict__.keys()):
        #     setattr(folw, key+'_tp1', soln_futr.pars.__dict__[key])

        self.soln_crnt.bilt.stge_kind = \
            self.soln_crnt.stge_kind = {'iter_status': 'iterator',
                                        'slvr_type': self.__class__.__name__}

        return

    # Disambiguate "prepare_to_solve" from similar method names elsewhere
    # (preserve "prepare_to_solve" as alias because core.py calls it)
    prepare_to_solve = solver_prep_solution_for_an_iteration


##############################################################################

class ConsPerfForesightSolver(ConsPerfForesightSolverEOP):
    def __init__(
            self, solution_next, DiscFac=1.0, LivPrb=1.0, CRRA=2.0, Rfree=1.0,
            PermGroFac=1.0, BoroCnstArt=None, MaxKinks=None, **kwds
    ):
        super().__init__(solution_next, DiscFac=DiscFac, LivPrb=LivPrb, CRRA=CRRA,
                         Rfree=Rfree, PermGroFac=PermGroFac,
                         BoroCnstArt=BoroCnstArt, MaxKinks=MaxKinks, **kwds)


class ConsIndShockSetupEOP(ConsPerfForesightSolver):
    """
    A superclass for solvers of one period consumption-saving problems with
    constant relative risk aversion utility and permanent and transitory shocks
    to income, containing code shared among alternative specific solvers.
    Has methods to set up but not solve the one period problem.

    N.B.: Because this is a one stge solver, objects that (in the full problem)
    are lists because they are allowed to vary at different stages, are scalars
    here because the value that is appropriate for the current stage is the one
    that will be passed.

    Parameters
    ----------
    solution_next : ConsumerSolution
        The solution to next period's one period problem.
    IncShkDstn : distribution.Distribution
        A discrete approximation to the income process between the period
        being solved and the one immediately following
    LivPrb : float
        Survival probability; likelihood of being alive at the beginning of
        the succeeding period.
    DiscFac : float
        Intertemporal discount factor for future utility.
    CRRA : float
        Coefficient of relative risk aversion.
    Rfree : float
        Risk free interest factor on end-of-period assets.
    PermGroFac : float
        Expected permanent income growth factor at the end of this period.
    BoroCnstArt: float or None
        Borrowing constraint for the minimum allowable assets to end the
        period with.  If it is less than the natural borrowing constraint,
        then it is irrelevant; BoroCnstArt=None indicates no artificial bor-
        rowing constraint.
    aXtraGrid: np.array
        Array of "extra" end-of-period asset values-- assets above the
        absolute minimum acceptable level.
    vFuncBool: boolean
        An indicator for whether the value function should be computed and
        included in the reported soln_crnt.
    CubicBool: boolean
        An indicator for whether the solver should use cubic or linear inter-
        polation.
    """
    shock_vars = ['tranShkDstn', 'permShkDstn']  # Unemp shock is min(transShkVal)

    # TODO: CDC 20210416: Params shared with PF are in different order. Fix
    def __init__(
            self, solution_next, IncShkDstn, LivPrb, DiscFac, CRRA, Rfree, PermGroFac, BoroCnstArt, aXtraGrid, vFuncBool,
            CubicBool, permShkDstn, tranShkDstn, **kwds
    ):  # First execute PF solver init
        # We must reorder params by hand in case someone tries positional solve
        #        breakpoint()
        ConsPerfForesightSolver.__init__(self, solution_next, DiscFac=DiscFac, LivPrb=LivPrb, CRRA=CRRA,
                                         Rfree=Rfree, PermGroFac=PermGroFac, BoroCnstArt=BoroCnstArt, IncShkDstn=IncShkDstn, permShkDstn=permShkDstn,
                                         tranShkDstn=tranShkDstn, **kwds
                                         )

        # ConsPerfForesightSolver.__init__ makes self.soln_crnt

        soln_crnt = self.soln_crnt

        # Don't want to keep track of anything on self of disposable solver
        bilt = soln_crnt.bilt  # things that are built
        pars = soln_crnt.pars  # parameters are exogenous

        bilt.aXtraGrid = aXtraGrid
        bilt.vFuncBool = vFuncBool
        bilt.CubicBool = CubicBool

        # In which column is each object stored in IncShkDstn?
        pars.permPos = IncShkDstn.parameters['ShkPosn']['perm']
        pars.tranPos = IncShkDstn.parameters['ShkPosn']['tran']

        # Bcst are "broadcasted" values: serial list of every possible combo
        # Makes it easy to take expectations using 𝔼_dot
        pars.permShkValsBcst = permShkValsBcst = IncShkDstn.X[pars.permPos]
        pars.tranShkValsBcst = tranShkValsBcst = IncShkDstn.X[pars.tranPos]

        pars.ShkPrbs = ShkPrbs = IncShkDstn.pmf

        pars.permShkPrbs = permShkPrbs = permShkDstn.pmf
        pars.permShkVals = permShkVals = permShkDstn.X
        # Confirm that perm shocks have expectation near one
        assert_approx_equal(𝔼_dot(permShkPrbs, permShkVals), 1.0)

        pars.tranShkPrbs = tranShkPrbs = tranShkDstn.pmf
        pars.tranShkVals = tranShkVals = tranShkDstn.X
        # Confirm that tran shocks have expectation near one
        assert_approx_equal(𝔼_dot(tranShkPrbs, tranShkVals), 1.0)

        pars.permShkMin = permShkMin = np.min(permShkVals)
        pars.tranShkMin = tranShkMin = np.min(tranShkVals)

        pars.permShkMax = permShkMax = np.max(permShkVals)
        pars.tranShkMax = tranShkMax = np.max(tranShkVals)

        pars.UnempPrb = pars.tranShkPrbs[0]

        pars.inc_min_Prb = np.sum(  # All cases where perm and tran Shk are Min
            ShkPrbs[ \
                permShkValsBcst * tranShkValsBcst == permShkMin * tranShkMin
            ]
        )

        pars.inc_max_Prb = np.sum(  # All cases where perm and tran Shk are Min
            ShkPrbs[ \
                permShkValsBcst * tranShkValsBcst == permShkMax * tranShkMax
            ]
        )
        pars.inc_max_Val = permShkMax * tranShkMax

    def build_infhor_facts_from_params(self):
        """
        For versions with uncertainty in transitory and/or permanent shocks,
        adds to the solution a set of results useful for calculating
        various diagnostic conditions about the problem, and stable
        points (if they exist).

        Parameters
        ----------
        solution: ConsumerSolution
            Solution to this period's problem, which must have attribute cFunc.

        Returns
        -------
        solution : ConsumerSolution
            Same solution that was provided, augmented with the factors

        """
        super().build_infhor_facts_from_params()
        soln_crnt = self.soln_crnt

        bilt, folw, pars = soln_crnt.bilt, soln_crnt.folw, soln_crnt.pars

        E_t = soln_crnt.E_t

        # The 'givens' do not change as facts are constructed
        givens = {**folw.__dict__, **pars.__dict__, **soln_crnt.__dict__}

        bilt.𝔼_dot = 𝔼_dot  # add the expectations operator to envt
        bilt.E_dot = E_dot  # plain not doublestruck E

        urlroot = bilt.urlroot
        # Modify formulae also present in PF model but that must change

        # Many other _fcts will have been inherited from the perfect foresight
        # model of which this model is a descendant
        # Here we need compute only those objects whose value changes
        # or does not exist when the shock distributions are degenerate.

        E_t.IncNrmNxt_fcts = {
            'about': 'Expected income next period'
        }
        py___code = '𝔼_dot(ShkPrbs,tranShkValsBcst * permShkValsBcst)'
        E_t.IncNrmNxt = E_t.IncNrmNxt = eval(
            py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        E_t.IncNrmNxt_fcts.update({'latexexpr': r'ExIncNrmNxt'})
        E_t.IncNrmNxt_fcts.update({'_unicode_': r'𝔼[tranShk permShk] = 1.0'})
        E_t.IncNrmNxt_fcts.update({'urlhandle': urlroot+'ExIncNrmNxt'})
        E_t.IncNrmNxt_fcts.update({'py___code': py___code})
        E_t.IncNrmNxt_fcts.update({'value_now': E_t.IncNrmNxt})
        soln_crnt.E_t.IncNrmNxt_fcts = E_t.IncNrmNxt_fcts

        E_t.Inv_permShk_fcts = {
            'about': 'Expected Inverse of Permanent Shock'
        }
        py___code = '𝔼_dot(1/permShkVals, permShkPrbs)'
        E_t.Inv_permShk = E_t.Inv_permShk = eval(
            py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        E_t.Inv_permShk_fcts.update({'latexexpr': r'\ExInvpermShk'})
        E_t.Inv_permShk_fcts.update({'urlhandle': urlroot+'ExInvpermShk'})
        E_t.Inv_permShk_fcts.update({'py___code': py___code})
        E_t.Inv_permShk_fcts.update({'value_now': E_t.Inv_permShk})
        soln_crnt.E_t.Inv_permShk_fcts = E_t.Inv_permShk_fcts

        E_t.RNrm_fcts = {
            'about': 'Expected Stochastic-Growth-Normalized Return'
        }
        py___code = 'RNrm_PF * E_t.Inv_permShk'
        E_t.RNrm = eval(
            py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        E_t.RNrm_fcts.update({'latexexpr': r'\ExRNrm'})
        E_t.RNrm_fcts.update({'_unicode_': r'𝔼[R/Γψ]'})
        E_t.RNrm_fcts.update({'urlhandle': urlroot+'ExRNrm'})
        E_t.RNrm_fcts.update({'py___code': py___code})
        E_t.RNrm_fcts.update({'value_now': E_t.RNrm})
        E_t.RNrm_fcts = E_t.RNrm_fcts

        E_t.uInv_permShk_fcts = {
            'about': 'Expected Utility for Consuming Permanent Shock'
        }
        py___code = '𝔼_dot(permShkValsBcst**(1-CRRA), ShkPrbs)'
        E_t.uInv_permShk = E_t.uInv_permShk = eval(
            py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        E_t.uInv_permShk_fcts.update({'latexexpr': r'\ExuInvpermShk'})
        E_t.uInv_permShk_fcts.update({'urlhandle': r'ExuInvpermShk'})
        E_t.uInv_permShk_fcts.update({'py___code': py___code})
        E_t.uInv_permShk_fcts.update({'value_now': E_t.uInv_permShk})
        E_t.uInv_permShk_fcts = E_t.uInv_permShk_fcts

        GPFNrm_fcts = {
            'about': 'Normalized Expected Growth Patience Factor'
        }
        py___code = 'GPFRaw * E_t.Inv_permShk'
        bilt.GPFNrm = eval(py___code, {},
                           {**E_t.__dict__, **bilt.__dict__, **givens})
        GPFNrm_fcts.update({'latexexpr': r'\GPFNrm'})
        GPFNrm_fcts.update({'_unicode_': r'Þ_Γ'})
        GPFNrm_fcts.update({'urlhandle': urlroot+'GPFNrm'})
        GPFNrm_fcts.update({'py___code': py___code})
        bilt.GPFNrm_fcts = GPFNrm_fcts

        GICNrm_fcts = {
            'about': 'Stochastic Growth Normalized Impatience Condition'
        }
        GICNrm_fcts.update({'latexexpr': r'\GICNrm'})
        GICNrm_fcts.update({'urlhandle': urlroot+'GICNrm'})
        GICNrm_fcts.update({'py___code': 'test: GPFNrm < 1'})
        bilt.GICNrm_fcts = GICNrm_fcts

        FVAC_fcts = {  # overwrites PF version
            'about': 'Finite Value of Autarky Condition'
        }

        FVAF_fcts = {  # overwrites PF version FVAFPF
            'about': 'Finite Value of Autarky Factor'
        }
        py___code = 'LivPrb * DiscLiv'
        bilt.FVAF = eval(py___code, {},
                         {**E_t.__dict__, **bilt.__dict__, **givens})
        FVAF_fcts.update({'latexexpr': r'\FVAF'})
        FVAF_fcts.update({'urlhandle': urlroot+'FVAF'})
        FVAF_fcts.update({'py___code': py___code})
        bilt.FVAF_fcts = FVAF_fcts

        FVAC_fcts = {  # overwrites PF version
            'about': 'Finite Value of Autarky Condition'
        }
        FVAC_fcts.update({'latexexpr': r'\FVAC'})
        FVAC_fcts.update({'urlhandle': urlroot+'FVAC'})
        FVAC_fcts.update({'py___code': 'test: FVAF < 1'})
        bilt.FVAC_fcts = FVAC_fcts

        WRPF_fcts = {
            'about': 'Weak Return Patience Factor'
        }
        py___code = '(UnempPrb ** (1 / CRRA)) * RPF'
        bilt.WRPF = WRPF = eval(py___code, {},
                                {**E_t.__dict__, **bilt.__dict__, **givens})
        WRPF_fcts.update({'latexexpr': r'\WRPF'})
        WRPF_fcts.update({'_unicode_': r'℘^(1/\rho) RPF'})
        WRPF_fcts.update({'urlhandle': urlroot+'WRPF'})
        WRPF_fcts.update({'value_now': WRPF})
        WRPF_fcts.update({'py___code': py___code})
        bilt.WRPF_fcts = WRPF_fcts

        WRIC_fcts = {
            'about': 'Weak Return Impatience Condition'
        }
        WRIC_fcts.update({'latexexpr': r'\WRIC'})
        WRIC_fcts.update({'urlhandle': urlroot+'WRIC'})
        WRIC_fcts.update({'py___code': 'test: WRPF < 1'})
        bilt.WRIC_fcts = WRIC_fcts

        DiscGPFNrmCusp_fcts = {
            'about': 'DiscFac s.t. GPFNrm = 1'
        }
        py___code = '((PermGroFac/E_t.Inv_permShk)**(CRRA))/Rfree'
        bilt.DiscGPFNrmCusp = DiscGPFNrmCusp = \
            eval(py___code, {}, {**E_t.__dict__, **bilt.__dict__, **givens})
        DiscGPFNrmCusp_fcts.update({'latexexpr': ''})
        DiscGPFNrmCusp_fcts.update({'value_now': DiscGPFNrmCusp})
        DiscGPFNrmCusp_fcts.update({'py___code': py___code})
        bilt.DiscGPFNrmCusp_fcts = DiscGPFNrmCusp_fcts

    def build_recursive_facts(self):
        super().build_recursive_facts()

        soln_crnt = self.soln_crnt
        bilt = soln_crnt.bilt
        pars = soln_crnt.pars
        E_t = soln_crnt.E_t

        # Now define some useful lambda functions
        # To use these it is necessary to have created an alias to
        # the relevant namespace on the solution object, e.g.
        # E_t = [soln].E_t
        # bilt = [soln].bilt
        # pars = [soln].pars

        # Given m, value of c where 𝔼[m_{t+1}]=m_{t}
        E_t.m_tp1_minus_m_t_eq_0 = (
            lambda m_t:
            m_t * (1 - 1/E_t.RNrm) + (1/E_t.RNrm)
        )

        # Given m, value of c where 𝔼[mLev_{t+1}/mLev_{t}]=bilt.pars.permGroFac
        # Solves for c in equation at url/#balgrostable

        E_t.permShk_times_m_tp1_minus_m_t_eq_0 = (
            lambda m_t:
            m_t * (1 - E_t.Inv_RNrm_PF) + E_t.Inv_RNrm_PF
        )

        # 𝔼[m_{t+1} pLev_{t+1}/pLev_{t}] as a fn of a_{t}
        E_t.mLev_tp1_Over_pLev_t_from_a_t = (
            lambda a_t:
            𝔼_dot(pars.PermGroFac *
                  pars.permShkValsBcst *
                  (E_t.RNrm_PF/pars.permShkValsBcst) * a_t + pars.tranShkValsBcst,
                  pars.ShkPrbs)
        )

        # 𝔼[c_{t+1} pLev_{t+1}/pLev_{t}] as a fn of a_{t}
        E_t.cLev_tp1_Over_pLev_t_from_a_t = (
            lambda a_t:
            𝔼_dot(pars.PermGroFac *
                  pars.permShkValsBcst *
                  bilt.cFunc((E_t.RNrm_PF/pars.permShkValsBcst) * a_t + pars.tranShkValsBcst),
                  pars.ShkPrbs)
        )

        E_t.c_where_E_t_m_tp1_minus_m_t_eq_0 = \
            lambda m_t: \
            m_t * (1 - 1/E_t.RNrm) + (1/E_t.RNrm)

        # Solve the equation at url/#balgrostable
        E_t.c_where_E_t_permShk_times_m_tp1_minus_m_t_eq_0 = \
            lambda m_t: \
            (m_t * (1 - 1/E_t.RNrm_PF)) + (1/E_t.RNrm_PF)

        # mNrmTrg solves E_t.RNrm*(m - c(m)) + 𝔼[inc_next] - m = 0
        E_t.m_tp1_minus_m_t = (
            lambda m_t:
            E_t.RNrm * (m_t - bilt.cFunc(m_t)) + E_t.IncNrmNxt - m_t
        )

        E_t.cLev_tp1_Over_pLev_t_from_num_a_t = (
            lambda a_t:
            𝔼_dot(
                pars.permShkValsBcst * pars.PermGroFac * bilt.cFunc(
                    (E_t.RNrm_PF/pars.permShkValsBcst) *
                    a_t + pars.tranShkValsBcst
                ),
                pars.ShkPrbs)
        )

        E_t.cLev_tp1_Over_pLev_t_from_lst_a_t = (
            lambda a_lst: list(map(
                E_t.cLev_tp1_Over_pLev_t_from_num_a_t, a_lst
            ))
        )

        E_t.cLev_tp1_Over_pLev_t_from_a_t = (
            lambda a_t:
            E_t.cLev_tp1_Over_pLev_t_from_lst_a_t(a_t)
            if (type(a_t) == list or type(a_t) == np.ndarray) else
            E_t.cLev_tp1_Over_pLev_t_from_num_a_t(a_t)
        )

        E_t.cLev_tp1_Over_pLev_t_from_lst_m_t = (
            lambda m_t:
            E_t.cLev_tp1_Over_pLev_t_from_lst_a_t(m_t -
                                                  bilt.cFunc(m_t))
        )

        E_t.cLev_tp1_Over_pLev_t_from_num_m_t = (
            lambda m_t:
            E_t.cLev_tp1_Over_pLev_t_from_num_a_t(m_t -
                                                  bilt.cFunc(m_t))
        )

        E_t.cLev_tp1_Over_cLev_t_from_m_t = (
            lambda m_t:
            E_t.cLev_tp1_Over_pLev_t_from_lst_m_t(m_t) / bilt.cFunc(m_t)
            if (type(m_t) == list or type(m_t) == np.ndarray) else
            E_t.cLev_tp1_Over_pLev_t_from_num_m_t(m_t) / bilt.cFunc(m_t)
        )

        E_t.permShk_tp1_times_m_tp1_minus_m_t = (
            lambda m_t:
            E_t.RNrm_PF * (m_t - bilt.cFunc(m_t)) + E_t.IncNrmNxt - m_t
        )

        self.soln_crnt = soln_crnt

        return soln_crnt


class ConsIndShockSetup(ConsIndShockSetupEOP):
    pass


class ConsIndShockSetup_ex_ante(ConsIndShockSetup):
    pass

#############################################################################


class ConsIndShockSolverBasic_ex_ante(ConsIndShockSetup_ex_ante):
    def __init__(self, *args, **kwds):
        super().init(self, *args, **kwds)

    def make_ex_ante_states_from_transition_eqns_inverse(self):
        givens = {}
        E_t = self.soln_crnt.E_t
        bilt = self.soln_crnt.bilt
        for key in self.transition_eqns_inverse.keys():
            eval(self.transition_eqns_inverse[key], {}, {
                 **E_t.__dict__, **bilt.__dict__, **givens})

    def make_ex_ante_states(self):
        bilt = self.soln_crnt.bilt
        aNrmMin_tm1 = bilt.BoroCnstNat*(bilt.PermGroFac*bilt.permShkMax)/bilt.Rfree
        bilt.aNrmGrid_tm1 = np.asarray(bilt.aXtraGrid) + aNrmMin_tm1

    def add_E_tm1_v_t(self):
        bilt = self.soln_crnt.bilt
        pars = self.soln_crnt.pars
        IncShkDstn = pars.IncShkDstn
        aNrmGrid_tm1 = bilt.aNrmGrid_tm1

        def vals_given_shocks_v_t(xfer_shks_bcst, curr_post_states):
            return xfer_shks_bcst[pars.permPos] ** (1-pars.CRRA - 0.0) * \
                self.soln_crnt.vFunc(
                    self.mNrm_t_from_a_tm1_bcst(xfer_shks_bcst, curr_post_states))

        def vals_given_shocks_v_t_dm(xfer_shks_bcst, curr_post_states):
            return xfer_shks_bcst[pars.permPos] ** (1-pars.CRRA - 1.0) * \
                self.soln_crnt.vFunc.dm(
                    self.mNrm_t_from_a_tm1_bcst(xfer_shks_bcst, curr_post_states))

        def vals_given_shocks_v_t_dm_dm(xfer_shks_bcst, curr_post_states):
            return xfer_shks_bcst[pars.permPos] ** (1-pars.CRRA - 2.0) * \
                self.soln_crnt.vFunc.dm.dm(
                    self.mNrm_t_from_a_tm1_bcst(xfer_shks_bcst, curr_post_states))

        def vals_given_shocks_v_t_derivatives_012(xfer_shks_bcst, curr_post_states):
            return np.array([vals_given_shocks_v_t(xfer_shks_bcst, curr_post_states),
                             vals_given_shocks_v_t_dm(xfer_shks_bcst, curr_post_states),
                             vals_given_shocks_v_t_dm_dm(xfer_shks_bcst, curr_post_states)])

        E_t = self.soln_crnt.E_t
        E_t.ante.v_t = np.squeeze(
            * pars.Rfree
            * pars.PermGroFac ** (-pars.CRRA)
            * calc_expectation_of_array(
                IncShkDstn,
                vals_given_shocks_v_t_derivatives_012,
                aNrmGrid_tm1
            )
        )


class ConsIndShockSolverBasicEOP(ConsIndShockSetupEOP):
    """
    This class solves a single period of a standard consumption-saving problem,
    using linear interpolation and without the ability to calculate the value
    function.  ConsIndShockSolver inherits from this class and adds the ability
    to perform cubic interpolation and to calculate the value function.

    Note that this class does not have its own initializing method.  It initial-
    izes the same problem in the same way as ConsIndShockSetup, from which it
    inherits.
    """

    def make_ending_states(self):
        """
        Prepare to calculate end-of-period marginal value by creating an array
        of market resources that the agent could have next period, given the
        current grid of end-of-period assets and the distribution of shocks
        they might experience next period.

        Parameters
        ----------
        none

        Returns
        -------
        aNrmGrid : np.array
            A 1D array of end-of-period assets; also stored as attribute of self.soln_crnt.bilt.
        """

        # We define aNrmGrid all the way from BoroCnstNat up to max(aXtraGrid)
        # even if BoroCnstNat < BoroCnstArt, so we can construct the consumption
        # function as the lower envelope of the (by the artificial borrowing con-
        # straint) unconstrained consumption function, and the artificially con-
        # strained consumption function.
        self.soln_crnt.bilt.aNrmGrid = np.asarray(
            self.soln_crnt.bilt.aXtraGrid) + self.soln_crnt.bilt.BoroCnstNat

        return self.soln_crnt.bilt.aNrmGrid

    def add_Post_Choice_Value(self):
        """
        Calculate expected value after choices but before shocks.
        """

        soln_crnt = self.soln_crnt
        futr = self.soln_futr

        bilt, pars, folw, E_t = \
            soln_crnt.bilt, soln_crnt.pars, soln_crnt.folw, soln_crnt.E_t

        IncShkDstn = pars.IncShkDstn
        aNrmGrid = bilt.aNrmGrid
        CRRA_tp1 = futr.vFunc.CRRA
        Rfree = pars.Rfree

        def post_t_E_v_tp1_wrapped(dstn, aNrm):
            CRRA = folw.vFunc_tp1.CRRA
            permPos = dstn.parameters['ShkPosn']['perm']
            tranPos = dstn.parameters['ShkPosn']['tran']
            permShk = dstn.X[permPos]
            tranShk = dstn.X[tranPos]
            mNrm_tp1_from_a_t_by_shk = \
                (pars.Rfree / (pars.PermGroFac * permShk)) * aNrm + tranShk
            v_tp1_vals = self.soln_crnt.folw.vFunc_tp1(mNrm_tp1_from_a_t_by_shk)
            v_NormFac_vals = permShk**(1-CRRA_tp1 - 0.0)
            E_t_v_tp1_vals = v_NormFac_vals * v_tp1_vals
            return E_t_v_tp1_vals

        def post_t_E_v_tp1(xfer_shks_bcst, curr_post_states):
            mNrm_tp1 = self.next_ante_states(xfer_shks_bcst, curr_post_states).mNrm
            return (pars.DiscLiv *
                    xfer_shks_bcst[pars.permPos] ** (1-CRRA_tp1 - 0) *
                    futr.vFunc(mNrm_tp1))

        def post_t_E_v_tp1_da_t(xfer_shks_bcst, curr_post_states):
            mNrm_tp1 = self.next_ante_states(xfer_shks_bcst, curr_post_states).mNrm
            return (pars.DiscLiv * pars.Rfree *
                    xfer_shks_bcst[pars.permPos] ** (0-CRRA_tp1 - 0) *
                    futr.vFunc.dm(mNrm_tp1))

        def post_t_E_v_tp1_da_t_da_t(xfer_shks_bcst, curr_post_states):
            mNrm_tp1 = self.next_ante_states(xfer_shks_bcst, curr_post_states).mNrm
            return (pars.DiscLiv * pars.Rfree * pars.Rfree *
                    xfer_shks_bcst[pars.permPos] ** (0-CRRA_tp1 - 1) *
                    futr.vFunc.dm.dm(mNrm_tp1))

        def v_post_choice_t(xfer_shks_bcst, curr_post_states):
            tp1 = self.next_ante_states(xfer_shks_bcst, curr_post_states)
            mNrm_tp1 = tp1.mNrm
            PermGro = xfer_shks_bcst[pars.permPos]*pars.PermGroFac
            DiscLiv = pars.DiscLiv
            v_0 = PermGro ** (1-CRRA_tp1 - 0) * futr.vFunc(mNrm_tp1) * DiscLiv 
            v_1 = PermGro ** (1-CRRA_tp1 - 1) * futr.vFunc.dm(mNrm_tp1) * Rfree * DiscLiv 
            v_2 = PermGro ** (1-CRRA_tp1 - 2) * futr.vFunc.dm.dm(mNrm_tp1) * Rfree * Rfree * DiscLiv
#            breakpoint()
            return v_0, v_1, v_2

        def post_t_E_v_tp1_derivatives_012(xfer_shks_bcst, curr_post_states):
            return np.array([post_t_E_v_tp1(xfer_shks_bcst, curr_post_states),
                             post_t_E_v_tp1_da_t(xfer_shks_bcst, curr_post_states),
                             post_t_E_v_tp1_da_t_da_t(xfer_shks_bcst, curr_post_states)])

        # E_t.v_post_choice = np.squeeze(  # squeezes unused dimensions
        #     calc_expectation_of_array(
        #         IncShkDstn,
        #         post_t_E_v_tp1_derivatives_012,
        #         aNrmGrid)
        # )

        E_t.v_post_choice_t = np.squeeze(
            calc_expectation_of_array(
                IncShkDstn,
                v_post_choice_t,
                aNrmGrid)
#            * pars.DiscLiv
        )

#        breakpoint()

    def calc_EndOfPrdvP(self):
        """
        Calculate end-of-period marginal value of assets at each point in aNrm.
        Does so by taking a weighted sum of next period marginal values across
        income shocks (in a preconstructed grid self.soln_crnt.bilt.mNrmNext).

        Parameters
        ----------
        none

        Returns
        -------
        EndOfPrdvP : np.array
            A 1D array of end-of-period marginal value of assets
        """

        soln_crnt = self.soln_crnt
        bilt = soln_crnt.bilt
        folw = soln_crnt.folw
        pars = soln_crnt.pars
        E_t = soln_crnt.E_t

        IncShkDstn = pars.IncShkDstn
        aNrmGrid = bilt.aNrmGrid

        def post_t_v_tp1(xfer_shks_bcst, curr_post_states):
            CRRA = folw.vFunc_tp1.CRRA
            return (xfer_shks_bcst[pars.permPos] ** (1-CRRA)
                    * folw.vFunc_tp1(self.next_ante_states(xfer_shks_bcst, curr_post_states)))

        def post_t_vP_tp1(xfer_shks_bcst, curr_post_states):
            CRRA = folw.vFunc_tp1.CRRA
            return (xfer_shks_bcst[pars.permPos] ** (0-CRRA)
                    * folw.vFunc_tp1.dm(self.next_ante_states(xfer_shks_bcst, curr_post_states)))

        def post_t_v_tp1_dm(xfer_shks_bcst, curr_post_states):
            CRRA = folw.vFunc_tp1.CRRA
            return (xfer_shks_bcst[pars.permPos] ** (0-CRRA)
                    * folw.vFunc_tp1.dm(self.next_ante_states(xfer_shks_bcst, curr_post_states)))

        def post_t_v_tp1_dm_dm(xfer_shks_bcst, curr_post_states):
            CRRA = folw.vFunc_tp1.CRRA
            return (xfer_shks_bcst[pars.permPos] ** (0-CRRA - 1.0)
                    * folw.vFunc_tp1.dm.dm(self.next_ante_states(xfer_shks_bcst, curr_post_states)))

        def post_t_vDers_tp1(xfer_shks_bcst, curr_post_states):
            return np.array([post_t_v_tp1(xfer_shks_bcst, curr_post_states),
                             post_t_v_tp1_dm(xfer_shks_bcst, curr_post_states),
                             post_t_v_tp1_dm_dm(xfer_shks_bcst, curr_post_states)])

        EndOfPrdvP = (
            pars.DiscFac * pars.LivPrb
            * pars.Rfree
            * pars.PermGroFac ** (-pars.CRRA)
            * calc_expectation_of_array(
                IncShkDstn,
                post_t_vP_tp1,
                aNrmGrid
            )
        )
        # Get derivatives 0, 1, and 2 at the same time
        E_t.vDers_tp1 = np.squeeze(
            pars.DiscFac * pars.LivPrb
            * pars.Rfree
            * pars.PermGroFac ** (-pars.CRRA)
            * calc_expectation_of_array(
                IncShkDstn,
                post_t_vDers_tp1,
                aNrmGrid
            )
        )
        breakpoint()

        return EndOfPrdvP

    def get_source_points_via_EGM(self, EndOfPrdvP, aNrm):
        """
        Finds interpolation points (c,m) for the consumption function.

        Parameters
        ----------
        EndOfPrdvP : np.array
            Array of end-of-period marginal values.
        aNrm : np.array
            Array of end-of-period asset values that yield the marginal values
            in EndOfPrdvP.

        Returns
        -------
        c_for_interpolation : np.array
            Consumption points for interpolation.
        m_for_interpolation : np.array
            Corresponding market resource points for interpolation.
        """

#        cNrm = self.soln_crnt.bilt.uPinv(EndOfPrdvP)
        cNrm = self.soln_crnt.bilt.u.dc.Nvrs(EndOfPrdvP)
        mNrm = cNrm + aNrm

        # Limiting consumption is zero as m approaches mNrmMin
        c_for_interpolation = np.insert(cNrm, 0, 0.0, axis=-1)
        m_for_interpolation = np.insert(mNrm, 0, self.soln_crnt.bilt.BoroCnstNat, axis=-1)

        # Store these for calcvFunc
        self.soln_crnt.bilt.cNrm = cNrm
        self.soln_crnt.bilt.mNrm = mNrm

        return c_for_interpolation, m_for_interpolation

    def use_points_for_interpolation(self, cNrm, mNrm, interpolator):
        """
        Constructs a solution for this period, including the consumption
        function and marginal value function.

        Parameters
        ----------
        cNrm : np.array
            (Normalized) consumption points for interpolation.
        mNrm : np.array
            (Normalized) corresponding market resource points for interpolation.
        interpolator : function
            A function that constructs and returns a consumption function.

        Returns
        -------
        solution_interpolating : ConsumerSolution
            The solution to this period's consumption-saving problem, with a
            minimum m, a consumption function, and marginal value function.
        """
        bilt = self.soln_crnt.bilt
        pars = self.soln_crnt.pars
        # Use the given interpolator to construct the consumption function
        cFuncUnc = interpolator(mNrm, cNrm)  # Unc=Unconstrained

        # Combine the constrained and unconstrained functions into the true consumption function
        # by choosing the lower of the constrained and unconstrained functions
        # LowerEnvelope should only be used when BoroCnstArt is true
        if pars.BoroCnstArt is None:
            cFunc = cFuncUnc
        else:
            # CDC 20210614: LinearInterp and LowerEnvelope are both handmade
            # We should substitute standard ways to do these things
            # EconForge interpolation.py or scipy.interpolate for interpolation
            bilt.cFuncCnst = LinearInterp(
                np.array([bilt.mNrmMin, bilt.mNrmMin + 1.0]
                         ), np.array([0.0, 1.0]))
            cFunc = LowerEnvelope(cFuncUnc, bilt.cFuncCnst, nan_bool=False)

        # The marginal value function and the marginal marginal value function

        # Need to define vFunc so we can define vFunc.dm
        bilt.vFunc = vFunc = NullFunc()  # Not calculating the level of value -- yet

        # bilt.vPfunc = bilt.vFunc.dm = MargValueFuncCRRA(cFunc, pars.CRRA)
        bilt.vFunc.dm = vPfunc = MargValueFuncCRRA(cFunc, pars.CRRA)
        bilt.vFunc.dm.dm = MargMargValueFuncCRRA(bilt.cFunc, pars.CRRA)

        # Pack up the solution and return it
        solution_interpolating = ConsumerSolutionOneStateCRRA(
            cFunc=cFunc,
            vFunc=vFunc,
            vPfunc=vPfunc,
            mNrmMin=bilt.mNrmMin,
            CRRA=pars.CRRA
        )

        return solution_interpolating

    def interpolating_EGM_solution(self, EndOfPrdvP, aNrmGrid, interpolator):
        """
        Given end of period assets and end of period marginal value, construct
        the basic solution for this period.

        Parameters
        ----------
        EndOfPrdvP : np.array
            Array of end-of-period marginal values.
        aNrmGrid : np.array
            Array of end-of-period asset values that yield the marginal values
            in EndOfPrdvP.

        interpolator : function
            A function that constructs and returns a consumption function.

        Returns
        -------
        sol_EGM : ConsumerSolution
            The EGM solution to this period's consumption-saving problem, with a
            consumption function, marginal value function, and minimum m.
        """
        cNrm, mNrm = self.get_source_points_via_EGM(EndOfPrdvP, aNrmGrid)
        sol_EGM = self.use_points_for_interpolation(cNrm, mNrm, interpolator)

        return sol_EGM

    def make_sol_using_EGM(self):  # Endogenous Gridpts Method
        """
        Given a grid of end-of-period values of assets a, use the endogenous
        gridpoints method to obtain the corresponding values of consumption,
        and use the dynamic budget constraint to obtain the corresponding value
        of market resources m.

        Parameters
        ----------
        none (relies upon self.soln_crnt.aNrm existing before invocation)

        Returns
        -------
        solution : ConsumerSolution
            The solution to the single period consumption-saving problem.
        """
        bilt = self.soln_crnt.bilt
        uFunc = bilt.u
        E_t = self.soln_crnt.E_t
#        breakpoint()

#        self.add_Post_Choice_Value()  # Calculate v and its derivatives

        bilt.cNrmGrid = uFunc.dc.Nvrs(E_t.v_post_choice_t[1])  # [1]: first derivative

        # Construct a solution for this period
#        breakpoint()
        if bilt.CubicBool:
            soln_crnt = self.interpolating_EGM_solution(
                E_t.v_post_choice_t[1], bilt.aNrmGrid,
                interpolator=self.make_cubic_cFunc
            )
        else:
            soln_crnt = self.interpolating_EGM_solution(
                E_t.v_post_choice_t[1], bilt.aNrmGrid,
                interpolator=self.make_linear_cFunc
            )

        return soln_crnt

    def make_linear_cFunc(self, mNrm, cNrm):
        """
        Makes linear interpolation for the (unconstrained) consumption function.

        Parameters
        ----------
        mNrm : np.array
            Corresponding market resource points for interpolation.
        cNrm : np.array
            Consumption points for interpolation.

        Returns
        -------
        cFunc_unconstrained : LinearInterp
            The unconstrained consumption function for this period.
        """
        cFunc_unconstrained = LinearInterp(
            mNrm, cNrm, self.soln_crnt.bilt.cFuncLimitIntercept, self.soln_crnt.bilt.cFuncLimitSlope
        )
        return cFunc_unconstrained

    def solve_prepared_stage_E_IncShkDstn(self):
        """
        Calculate circumstances of an agent who has assets aNrm
        an instant before the realization of the shocks that constitute the 
        transition to the next period's state.

        Resulting solution object contains the value function vFunc and
        its derivatives.  Does not calculate consumption function cFunc:
        that is a consequence of vFunc.dm but is calculated in the
        stage that calls this one.

        Parameters
        ----------
        none (all should be on self)

        Returns
        -------
        solution : ConsumerSolution object
            Contains info (like vFunc.dm) required to construct consumption
        """

        # Add a bunch of useful info to solution object
        # CDC 20200428: "useful" only for a candidate converged solution
        # in an infinite horizon model.  It's virtually costless to compute but
        # not much point in computing it for a non-final infhor stage or finhor
        # TODO: Distinguish between those things that need to be computed for
        # "useful" computations in the final stage, and just info,
        # and make mandatory only the computations of the former category
        self.build_infhor_facts_from_params()
        self.build_recursive_facts()  # These require solution to successor

        # Current CRRA might be different from future
        soln_crnt = def_utility(self.soln_crnt, self.soln_crnt.pars.CRRA)
        soln_crnt = self.make_ending_states()
        self.add_Post_Choice_Value()
#        self.EndOfPrdvP = self.calc_EndOfPrdvP()

        return soln_crnt

    def solve_prepared_stage(self):  # solve ONE stage (ConsIndShockSolver)
        """
        Solves one period of the consumption-saving problem. 

        The ".bilt" namespace on the returned solution object includes
            * decision rule (consumption function), cFunc
            * value and marginal value functions vFunc and vFunc.dm
            * a minimum possible level of normalized market resources mNrmMin
            * normalized human wealth hNrm, and bounding MPCs MPCmin and MPCmax.

        If the user sets `CubicBool` to True, cFunc is interpolated
        with a Cubic Hermite interpolator.  This is much smoother than the default
        piecewise linear interpolator, and permits construction of the marginal
        marginal value function vFunc.dm.dm (which occurs automatically).

        In principle, the resulting cFunc will be numerically incorect at values 
        of market resources where a marginal increment to m would discretely 
        change the probability of a future constraint binding, because in 
        principle cFunc is nondifferentiable at those points.  In practice, if
        the distribution of shocks is not too granular, the approximation error
        is minor.

        Parameters
        ----------
        none (all should be on self)

        Returns
        -------
        solution : ConsumerSolution
            The solution to this period/stage's problem.
        """
        soln_crnt = self.soln_crnt
        CRRA = soln_crnt.pars.CRRA

        # The first invocation of ".solve" has iter_status='terminal_pseudo':
        # "pseudo" since it is not ready to serve as a proper starting point
        # for backward induction because further info (e.g., utility function)
        # must be added after solution_terminal was constructed.  Fix
        # by copying contents into the bilt attribute, then invoking the
        # build_infhor_facts_from_params() method to add the extra info

        # TODO CDC 20210615: This is a kludge to get things to work without modifying
        # core.py. Think about how to change core.py to address more elegantly
        if self.soln_futr.bilt.stge_kind['iter_status'] == 'terminal_pseudo':
            soln_crnt = def_utility(soln_crnt, CRRA)
            soln_crnt = def_value_funcs(soln_crnt, CRRA)
            soln_crnt.vFunc = self.soln_crnt.bilt.vFunc
            soln_crnt.cFunc = self.soln_crnt.bilt.cFunc

            # Now that it "knows itself" it can build the facts
            self.build_infhor_facts_from_params()

            # NOW mark as good-to-go as starting point for backward induction:
            self.soln_crnt.bilt.stge_kind['iter_status'] = 'iterator'

            return soln_crnt  # Replace original "terminal_pseudo" solution

        # Calculate everything about "saver" who ends period with aNrm
        self.solve_prepared_stage_E_IncShkDstn()

        # Notice that we could insert here a stage that would
        # solve any other problem that produces the state
        # variables needed for the self.solve_prepared_stage_E_IncShkDstn()
        # e.g., we could have:
        # self.solve_prepared_stage_E_RiskyReturnDistn
        # and before that a
        # self.solve_prepared_stage_calc_optimal_portfolio_share
        # and those would be the only changes needed to add the portfolio
        # choice model to this one

        # Having calculated (marginal value, etc) of saving, construct c

        sol_EGM = self.make_sol_using_EGM()
        soln_crnt.bilt.cFunc = soln_crnt.cFunc = sol_EGM.bilt.cFunc
        soln_crnt = def_value_funcs(soln_crnt, CRRA)  # add value funcs
        return soln_crnt

    solve = solve_prepared_stage

    def next_ante_states(self, xfer_shks_bcst, curr_post_states):
        """
        Returns array of values of normalized market resources m
        corresponding to permutations of potential realizations of
        the shocks, given the value of end-of-period assets aNrm.

        Parameters
        ----------
        xfer_shks_bcst: 2D ndarray
            Permanent and transitory income shocks.

        aNrm: float
            Normalized end-of-period assets this period

        Returns
        -------
        1D ndarray of m values conditional as a function of the
        2D ndarray of permanent and transitory shocks
           normalized market resources in the next period
        """
        pars = self.soln_crnt.pars
        permPos = pars.IncShkDstn.parameters['ShkPosn']['perm']
        tranPos = pars.IncShkDstn.parameters['ShkPosn']['tran']
        zeros = curr_post_states - curr_post_states  # adding zeros fixes size
        permShk = xfer_shks_bcst[permPos] + zeros
        tranShk = xfer_shks_bcst[tranPos] + zeros

        next_ante_states = Ante_Choice()
        aNrm = curr_post_states

#        breakpoint()
        eqns = self.soln_crnt.xfer_crnt_post_to_next_ante
        for key in eqns.keys():
            setattr(next_ante_states, key,
                    eval(eqns[key], {},
                         {**locals(),
                          **pars.__dict__,
                          **next_ante_states.__dict__})
                    )

        test = calc_expectation(self.soln_crnt.pars.IncShkDstn, lambda x,
                                y: x[0]+x[1]+y, self.soln_crnt.bilt.aNrmGrid)
        return next_ante_states
#        return pars.Rfree / (pars.PermGroFac * xfer_shks_bcst[permPos]) \
#            * curr_post_states + xfer_shks_bcst[tranPos]


class ConsIndShockSolverBasic(ConsIndShockSolverBasicEOP):
    pass


###############################################################################


class ConsIndShockSolverEOP(ConsIndShockSolverBasicEOP):
    """
    Solves a single period of a standard consumption-saving problem.
    It inherits from ConsIndShockSolverBasic, and adds ability to perform cubic
    interpolation and to calculate the value function.
    """

    def make_cubic_cFunc(self, mNrm_Vec, cNrm_Vec):
        """
        Makes a cubic spline interpolation of the unconstrained consumption
        function for this period.

        Requires self.soln_crnt.bilt.aNrm to have been computed already.

        Parameters
        ----------
        mNrm_Vec : np.array
            Corresponding market resource points for interpolation.
        cNrm_Vec : np.array
            Consumption points for interpolation.

        Returns
        -------
        cFunc_unconstrained : CubicInterp
            The unconstrained consumption function for this period.
        """

        soln_crnt = self.soln_crnt
        bilt, folw, pars, E_t = \
            soln_crnt.bilt, soln_crnt.folw, soln_crnt.pars, soln_crnt.E_t
        CRRA_tp1 = folw.vFunc_tp1.CRRA
#         breakpoint()

#         def vPP_tp1(xfer_shks_bcst, curr_post_states):
#             tp1 = self.next_ante_states(xfer_shks_bcst, curr_post_states)
#             mNrmGrid_tp1 = tp1.mNrm
#             return xfer_shks_bcst[pars.permPos] ** (- CRRA_tp1 - 1.0) \
#                 * folw.vPPfunc_tp1(mNrmGrid_tp1)

#         EndOfPrdvPP = (
#             pars.DiscFac * pars.LivPrb
#             * pars.Rfree
#             * pars.Rfree
#             * pars.PermGroFac ** (-CRRA_tp1 - 1.0)
#             * calc_expectation_of_array(
#                 pars.IncShkDstn,
#                 vPP_tp1,
#                 bilt.aNrmGrid
#             )
#         )

#         dcda = EndOfPrdvPP / bilt.uPP(np.array(cNrm_Vec[1:]))
# #        bilt.uPP(np.array(cNrm_Vec[1:]))

        dc_da = E_t.v_post_choice_t[2] / bilt.u.dc.dc(np.array(cNrm_Vec[1:]))
        # Second derivative
        MPC = dc_da / (dc_da + 1.0)
        MPC = np.insert(MPC, 0, bilt.MPCmax)

        cFuncUnc = CubicInterp(
            mNrm_Vec, cNrm_Vec, MPC, bilt.MPCmin *
            bilt.hNrm, bilt.MPCmin
        )
        return cFuncUnc


class ConsIndShockSolver(ConsIndShockSolverEOP):
    pass
