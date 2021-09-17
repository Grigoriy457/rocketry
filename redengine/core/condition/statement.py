
from copy import copy
from functools import partial
from abc import abstractmethod
import datetime
from typing import Optional
from redengine.core.time.base import TimePeriod
import time

import numpy as np

from .base import BaseCondition

import logging
logger = logging.getLogger(__name__)


class Statement(BaseCondition):
    """Base class for Statements.
    
    Statement is a base condition that
    require either inspecting historical
    events or doing a comparison of observed
    values to conclude whether the condition 
    holds.

    Parameters
    ----------
    *args : tuple
        Positional arguments for the ``observe``
        method.
    **kwargs : dict
        Keyword arguments for the ``observe``
        method.
    """

    name = None
    _use_global_params = False

    @classmethod
    def from_func(cls, func=None, *, historical=False, quantitative=False, str_repr=None, use_globals=False):
        """Generate statement from a function.

        The created statement is a subclass of 
        Statement and Historical (if historical=True)
        and Comparable (if quantitative=True).

        Parameters
        ----------
        func : Callable, optional
            The function to create the statement with, by default None
        historical : bool, optional
            Whether the statement has a time window to check observation, 
            by default False
        quantitative : bool, optional
            Whether the statement can be compared (with <, >, ==, >=, etc.), 
            by default False
        str_repr : [type], optional
            [description], by default None
        use_globals : bool, optional
            Whether to allow passing session.parameters to the observe method, 
            by default False

        Returns
        -------
        Type
            Condition class.
        """
        if func is None:
            # Acts as decorator
            return partial(cls.from_func, historical=historical, quantitative=quantitative, use_globals=use_globals)

        name = func.__name__
        #bases = (cls,)

        bases = []
        if historical: 
            bases.append(Historical)
        if quantitative: 
            bases.append(Comparable)
        bases.append(cls)
        bases = tuple(bases)

        attrs = {
            "_use_global_params": use_globals,
            # Methods
            "observe": staticmethod(func),
        }

        # Creating class dynamically
        cls = type(
            name,
            tuple(bases),
            attrs
        )
        return cls

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __bool__(self):
        try:
            outcome = self.observe(*self.args, **self.get_kwargs())
            status = self._to_bool(outcome)
        except (KeyboardInterrupt, ImportError) as exc:
            # Let these through
            raise
        except Exception as exc:
            logger.exception(f"Statement '{self}' is False due to an Exception.")
            if self.session.config["debug"]:
                # Typically error is not good but we don't want to crash the whole production
                # due to a random error in one task's initiation. 
                # However, we do want to crash tests because of it.
                raise
            return False

        #logger.debug(f"Statement {str(self)} status: {status}")

        return status

    @abstractmethod
    def observe(self, *args, **kwargs):
        """Observe status of the statement (returns true/false).
        
        Override this to build own logic."""
        return True

    def _to_bool(self, res):
        return bool(res)

    def get_kwargs(self):
        # TODO: Get session parameters
        if self._use_global_params:
            return self.session.parameters | self.kwargs
        else:
            return self.kwargs

    def to_count(self, result):
        "Turn event result to quantitative number"
        if isinstance(result, (int, float)):
            return result
        else:
            return len(result)
        
    def set_params(self, *args, **kwargs):
        "Add arguments to the experiment"
        self.args = (*self.args, *args)
        self.kwargs.update(kwargs)

    def __str__(self):
        name = self.name
        return f"< Statement '{name}'>"

    def copy(self):
        # Cannot deep copy self as if task is in kwargs, failure occurs
        new = copy(self)
        new.kwargs = copy(new.kwargs)
        new.args = copy(new.args)
        return new

    def __eq__(self, other):
        "Equal operation"
        is_same_class = isinstance(other, type(self))
        if is_same_class:
            has_same_args = self.args == other.args
            has_same_kwargs = self.kwargs == other.kwargs
            return has_same_args and has_same_kwargs
        else:
            return False

    def __repr__(self):
        cls_name = type(self).__name__
        arg_str = ', '.join(map(repr, self.args))
        kwargs_str = ', '.join(f'{key}={repr(val)}' for key, val in self.kwargs.items())
        param_str = ""
        if arg_str:
            param_str = arg_str
        if kwargs_str:
            if param_str:
                param_str = param_str + ", "
            param_str = param_str + kwargs_str
        return f'{cls_name}({param_str})'


class Comparable(Statement):
    """Statement that can be compared.

    The ``.observe()`` method should 
    return either:

    - boolean: Whether the value is true or false
    - Iterable: inspected whether the length fulfills the given comparisons.
    - int, float: inspected whether the number fulfills the given comparisons. 

    Parameters
    ----------
    *args : tuple
        See ``Statement``.
    **kwargs : dict
        See ``Statement``.
    """

    def _to_bool(self, res):
        if isinstance(res, bool):
            return super()._to_bool(res)

        res = len(res) if hasattr(res, "__len__") else res

        comps = {
            f"_{comp}_": self.kwargs[comp]
            for comp in ("_eq_", "_ne_", "_lt_", "_gt_", "_le_", "_ge_")
            if comp in self.kwargs
        }
        if not comps:
            return res > 0
        return all(
            getattr(res, comp)(val) # Comparison is magic method (==, !=, etc.)
            for comp, val in comps.items()
        )

    def __eq__(self, other):
        # self == other
        is_same_class = isinstance(other, Comparable)
        if is_same_class:
            # Not storing as parameter to statement but
            # check whether the statements are same
            return super().__eq__(other)
        return self._set_comparison("_eq_", other)

    def __ne__(self, other):
        # self != other
        return self._set_comparison("_ne_", other)

    def __lt__(self, other):
        # self < other
        return self._set_comparison("_lt_", other)

    def __gt__(self, other):
        # self > other
        return self._set_comparison("_gt_", other)

    def __le__(self, other):
        # self <= other
        return self._set_comparison("_le_", other)
        
    def __ge__(self, other):
        # self >= other
        return self._set_comparison("_ge_", other)        

    def _set_comparison(self, key, val):
        obj = self.copy()
        obj.kwargs[key] = val
        return obj

    def get_kwargs(self):
        return super().get_kwargs()


class Historical(Statement):
    """Statement that has history.

    The ``.observe()`` method is supplemented with 
    (if period passed to init):

    - ``_start_``: Start time of the statement period
    - ``_end_``: End time of the statement period

    Parameters
    ----------
    *args : tuple
        See ``Statement``.
    period : TimePeriod
        Time period the statement should hold.
    **kwargs : dict
        See ``Statement``.
    """

    def __init__(self, *args, period:Optional[TimePeriod]=None, **kwargs):
        self.period = period
        super().__init__(*args, **kwargs)

    def get_kwargs(self):
        kwargs = super().get_kwargs()
        if self.period is None:
            return kwargs

        dt = datetime.datetime.fromtimestamp(time.time())

        interval = self.period.rollback(dt)
        start = interval.left
        end = interval.right
        kwargs["_start_"] = start
        kwargs["_end_"] = end
        return kwargs

    def __eq__(self, other):
        # self == other
        is_same_class = isinstance(other, type(self))
        if is_same_class:
            # Not storing as parameter to statement but
            # check whether the statements are same
            has_same_period = self.period == other.period
            return super().__eq__(other) and has_same_period
        return super().__eq__(other)

    def __repr__(self):
        string = super().__repr__()
        period = self.period
        if period is not None:
            base_string = string[:-1]
            if base_string[-1] != "(":
                base_string = base_string + ", "
            return base_string + f"period={repr(self.period)})"
        else:
            return string