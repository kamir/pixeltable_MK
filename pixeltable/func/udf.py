from __future__ import annotations

from typing import Any, Callable, Optional, Sequence, overload

import pixeltable.exceptions as excs
import pixeltable.type_system as ts

from .callable_function import CallableFunction
from .expr_template_function import ExprTemplateFunction, ExprTemplate
from .function import Function
from .function_registry import FunctionRegistry
from .globals import validate_symbol_path
from .signature import Signature


# Decorator invoked without parentheses: @pxt.udf
@overload
def udf(decorated_fn: Callable) -> CallableFunction: ...


# Decorator schema invoked with parentheses: @pxt.udf(**kwargs)
@overload
def udf(
    *,
    batch_size: Optional[int] = None,
    substitute_fn: Optional[Callable] = None,
    is_method: bool = False,
    is_property: bool = False,
    resource_pool: Optional[str] = None,
    type_substitutions: Optional[Sequence[dict]] = None,
    _force_stored: bool = False
) -> Callable[[Callable], CallableFunction]: ...


def udf(*args, **kwargs):
    """A decorator to create a Function from a function definition.

    Examples:
        >>> @pxt.udf
        ... def my_function(x: int) -> int:
        ...    return x + 1
    """
    if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):

        # Decorator invoked without parentheses: @pxt.udf
        # Simply call make_function with defaults.
        return make_function(decorated_fn=args[0])

    else:

        # Decorator schema invoked with parentheses: @pxt.udf(**kwargs)
        # Create a decorator for the specified schema.
        batch_size = kwargs.pop('batch_size', None)
        substitute_fn = kwargs.pop('substitute_fn', None)
        is_method = kwargs.pop('is_method', None)
        is_property = kwargs.pop('is_property', None)
        resource_pool = kwargs.pop('resource_pool', None)
        type_substitutions = kwargs.pop('type_substitutions', None)
        force_stored = kwargs.pop('_force_stored', False)
        if len(kwargs) > 0:
            raise excs.Error(f'Invalid @udf decorator kwargs: {", ".join(kwargs.keys())}')
        if len(args) > 0:
            raise excs.Error('Unexpected @udf decorator arguments.')

        def decorator(decorated_fn: Callable):
            return make_function(
                decorated_fn,
                batch_size=batch_size,
                substitute_fn=substitute_fn,
                is_method=is_method,
                is_property=is_property,
                resource_pool=resource_pool,
                type_substitutions=type_substitutions,
                force_stored=force_stored
            )

        return decorator


def make_function(
    decorated_fn: Callable,
    return_type: Optional[ts.ColumnType] = None,
    param_types: Optional[list[ts.ColumnType]] = None,
    batch_size: Optional[int] = None,
    substitute_fn: Optional[Callable] = None,
    is_method: bool = False,
    is_property: bool = False,
    resource_pool: Optional[str] = None,
    type_substitutions: Optional[Sequence[dict]] = None,
    function_name: Optional[str] = None,
    force_stored: bool = False
) -> CallableFunction:
    """
    Constructs a `CallableFunction` from the specified parameters.
    If `substitute_fn` is specified, then `decorated_fn`
    will be used only for its signature, with execution delegated to
    `substitute_fn`.
    """
    # Obtain function_path from decorated_fn when appropriate
    if force_stored:
        # force storing the function in the db
        function_path = None
    elif decorated_fn.__module__ != '__main__' and decorated_fn.__name__.isidentifier():
        function_path = f'{decorated_fn.__module__}.{decorated_fn.__qualname__}'
    else:
        function_path = None

    # Derive function_name, if not specified explicitly
    if function_name is None:
        function_name = decorated_fn.__name__

    # Display name to use for error messages
    errmsg_name = function_name if function_path is None else function_path

    signatures: list[Signature]
    if type_substitutions is None:
        sig = Signature.create(decorated_fn, param_types, return_type)

        # batched functions must have a batched return type
        # TODO: remove 'Python' from the error messages when we have full inference with Annotated types
        if batch_size is not None and not sig.is_batched:
            raise excs.Error(f'{errmsg_name}(): batch_size is specified; Python return type must be a `Batch`')
        if batch_size is not None and len(sig.batched_parameters) == 0:
            raise excs.Error(f'{errmsg_name}(): batch_size is specified; at least one Python parameter must be `Batch`')
        if batch_size is None and len(sig.batched_parameters) > 0:
            raise excs.Error(f'{errmsg_name}(): batched parameters in udf, but no `batch_size` given')

        if is_method and is_property:
            raise excs.Error(f'Cannot specify both `is_method` and `is_property` (in function `{function_name}`)')
        if is_property and len(sig.parameters) != 1:
            raise excs.Error(
                f"`is_property=True` expects a UDF with exactly 1 parameter, but `{function_name}` has {len(sig.parameters)}"
            )
        if (is_method or is_property) and function_path is None:
            raise excs.Error('Stored functions cannot be declared using `is_method` or `is_property`')

        signatures = [sig]
    else:
        if function_path is None:
            raise excs.Error(
                f'{errmsg_name}(): type substitutions can only be used with module UDFs (not locally defined UDFs)'
            )
        if batch_size is not None:
            raise excs.Error(f'{errmsg_name}(): type substitutions cannot be used with batched functions')
        if is_method is not None or is_property is not None:
            # TODO: Support this for `is_method`?
            raise excs.Error(f'{errmsg_name}(): type substitutions cannot be used with `is_method` or `is_property`')
        signatures = [
            Signature.create(decorated_fn, param_types, return_type, type_substitutions=subst)
            for subst in type_substitutions
        ]

    if substitute_fn is None:
        py_fn = decorated_fn
    else:
        if function_path is None:
            raise excs.Error(f'{errmsg_name}(): @udf decorator with a `substitute_fn` can only be used in a module')
        py_fn = substitute_fn

    result = CallableFunction(
        signatures=signatures,
        py_fns=[py_fn] * len(signatures),  # All signatures share the same Python function
        self_path=function_path,
        self_name=function_name,
        batch_size=batch_size,
        is_method=is_method,
        is_property=is_property
    )
    if resource_pool is not None:
        result.resource_pool(lambda: resource_pool)

    # If this function is part of a module, register it
    if function_path is not None:
        # do the validation at the very end, so it's easier to write tests for other failure scenarios
        validate_symbol_path(function_path)
        FunctionRegistry.get().register_function(function_path, result)

    return result

@overload
def expr_udf(py_fn: Callable) -> ExprTemplateFunction: ...

@overload
def expr_udf(*, param_types: Optional[list[ts.ColumnType]] = None) -> Callable[[Callable], ExprTemplateFunction]: ...

def expr_udf(*args: Any, **kwargs: Any) -> Any:
    def make_expr_template(py_fn: Callable, param_types: Optional[list[ts.ColumnType]]) -> ExprTemplateFunction:
        if py_fn.__module__ != '__main__' and py_fn.__name__.isidentifier():
            # this is a named function in a module
            function_path = f'{py_fn.__module__}.{py_fn.__qualname__}'
        else:
            function_path = None

        # TODO: verify that the inferred return type matches that of the template
        # TODO: verify that the signature doesn't contain batched parameters

        # construct Signature from the function signature
        sig = Signature.create(py_fn=py_fn, param_types=param_types, return_type=ts.InvalidType())
        import pixeltable.exprs as exprs
        var_exprs = [exprs.Variable(param.name, param.col_type) for param in sig.parameters.values()]
        # call the function with the parameter expressions to construct an Expr with parameters
        expr = py_fn(*var_exprs)
        assert isinstance(expr, exprs.Expr)
        sig.return_type = expr.col_type
        if function_path is not None:
            validate_symbol_path(function_path)
        return ExprTemplateFunction([ExprTemplate(expr, sig)], self_path=function_path, name=py_fn.__name__)

    if len(args) == 1:
        assert len(kwargs) == 0 and callable(args[0])
        return make_expr_template(args[0], None)
    else:
        assert len(args) == 0 and len(kwargs) == 1 and 'param_types' in kwargs
        return lambda py_fn: make_expr_template(py_fn, kwargs['param_types'])
