from typing import Callable, Any


def remove_all_args[T](fun: Callable[[], T], /) -> Callable[..., T]:

    def inner_fun(*args: Any, **kwargs: Any) -> T:
        _ = args, kwargs
        return fun()

    return inner_fun
