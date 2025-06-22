from mpyflow.shared.errors.exception import BootstrapEx
from pathlib import Path


def _check_rec_dir(path_given: Path, /) -> None:
    if str(path_given.suffix):
        raise BootstrapEx("No points in directory name allowed!")
    if not path_given.exists():
        _check_rec_dir(path_given.parent)
    elif not path_given.is_dir():
        raise BootstrapEx("Path is not a directory!")


def _create_dirs_rec(path_given: Path, /) -> None:
    if not path_given.exists():
        _create_dirs_rec(path_given.parent)
    if not path_given.is_dir():
        path_given.mkdir()


def create_dirs_rec(path_given: Path, /) -> None:
    _check_rec_dir(path_given)
    _create_dirs_rec(path_given)
