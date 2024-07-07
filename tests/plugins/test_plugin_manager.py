from __future__ import annotations

import shutil

from pathlib import Path
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Protocol

import pytest

from cleo.io.buffered_io import BufferedIO
from cleo.io.outputs.output import Verbosity
from poetry.core.constraints.version import Version
from poetry.core.packages.dependency import Dependency
from poetry.core.packages.package import Package
from poetry.core.packages.project_package import ProjectPackage

from poetry.factory import Factory
from poetry.packages.locker import Locker
from poetry.plugins import ApplicationPlugin
from poetry.plugins import Plugin
from poetry.plugins.plugin_manager import PluginManager
from poetry.plugins.plugin_manager import ProjectPluginCache
from poetry.poetry import Poetry
from poetry.utils.env import Env
from poetry.utils.env import EnvManager
from poetry.utils.env import VirtualEnv
from tests.helpers import mock_metadata_entry_points


if TYPE_CHECKING:
    from cleo.io.io import IO
    from pytest_mock import MockerFixture

    from poetry.console.commands.command import Command
    from tests.conftest import Config
    from tests.types import FixtureDirGetter


class ManagerFactory(Protocol):
    def __call__(self, group: str = Plugin.group) -> PluginManager: ...


class MyPlugin(Plugin):
    def activate(self, poetry: Poetry, io: IO) -> None:
        io.write_line("Setting readmes")
        poetry.package.readmes = (Path("README.md"),)


class MyCommandPlugin(ApplicationPlugin):
    commands: ClassVar[list[type[Command]]] = []


class InvalidPlugin:
    def activate(self, poetry: Poetry, io: IO) -> None:
        io.write_line("Updating version")
        poetry.package.version = Version.parse("9.9.9")


@pytest.fixture
def system_env(tmp_venv: VirtualEnv, mocker: MockerFixture) -> Env:
    mocker.patch.object(EnvManager, "get_system_env", return_value=tmp_venv)
    return tmp_venv


@pytest.fixture
def poetry(fixture_dir: FixtureDirGetter, config: Config) -> Poetry:
    project_path = fixture_dir("simple_project")
    poetry = Poetry(
        project_path / "pyproject.toml",
        {},
        ProjectPackage("simple-project", "1.2.3"),
        Locker(project_path / "poetry.lock", {}),
        config,
    )

    return poetry


@pytest.fixture
def poetry_with_plugins(
    fixture_dir: FixtureDirGetter, config: Config, tmp_path: Path
) -> Poetry:
    orig_path = fixture_dir("project_plugins")
    project_path = tmp_path / "project"
    project_path.mkdir()
    shutil.copy(orig_path / "pyproject.toml", project_path / "pyproject.toml")
    return Factory().create_poetry(project_path)


@pytest.fixture()
def io() -> BufferedIO:
    return BufferedIO()


@pytest.fixture()
def manager_factory(poetry: Poetry, io: BufferedIO) -> ManagerFactory:
    def _manager(group: str = Plugin.group) -> PluginManager:
        return PluginManager(group)

    return _manager


@pytest.fixture
def with_my_plugin(mocker: MockerFixture) -> None:
    mock_metadata_entry_points(mocker, MyPlugin)


@pytest.fixture
def with_invalid_plugin(mocker: MockerFixture) -> None:
    mock_metadata_entry_points(mocker, InvalidPlugin)


def test_load_plugins_and_activate(
    manager_factory: ManagerFactory,
    poetry: Poetry,
    io: BufferedIO,
    with_my_plugin: None,
) -> None:
    manager = manager_factory()
    manager.load_plugins()
    manager.activate(poetry, io)

    assert poetry.package.readmes == (Path("README.md"),)
    assert io.fetch_output() == "Setting readmes\n"


def test_load_plugins_with_invalid_plugin(
    manager_factory: ManagerFactory,
    poetry: Poetry,
    io: BufferedIO,
    with_invalid_plugin: None,
) -> None:
    manager = manager_factory()

    with pytest.raises(ValueError):
        manager.load_plugins()


def test_ensure_plugins_no_plugins_no_output(poetry: Poetry, io: BufferedIO) -> None:
    PluginManager.ensure_project_plugins(poetry, io)

    assert not (poetry.pyproject_path.parent / ProjectPluginCache.PATH).exists()
    assert io.fetch_output() == ""
    assert io.fetch_error() == ""


def test_ensure_plugins_no_plugins_existing_cache_is_removed(
    poetry: Poetry, io: BufferedIO
) -> None:
    plugin_path = poetry.pyproject_path.parent / ProjectPluginCache.PATH
    plugin_path.mkdir(parents=True)

    PluginManager.ensure_project_plugins(poetry, io)

    assert not plugin_path.exists()
    assert io.fetch_output() == (
        "No project plugins defined. Removing the project's plugin cache\n\n"
    )
    assert io.fetch_error() == ""


@pytest.mark.parametrize("debug_out", [False, True])
def test_ensure_plugins_no_output_if_fresh(
    poetry_with_plugins: Poetry, io: BufferedIO, debug_out: bool
) -> None:
    io.set_verbosity(Verbosity.DEBUG if debug_out else Verbosity.NORMAL)
    cache = ProjectPluginCache(poetry_with_plugins, io)
    cache._write_config()

    cache.ensure_plugins()

    assert cache._config_file.exists()
    assert io.fetch_output() == (
        "The project's plugin cache is up to date.\n\n" if debug_out else ""
    )
    assert io.fetch_error() == ""


@pytest.mark.parametrize("debug_out", [False, True])
def test_ensure_plugins_ignore_irrelevant_markers(
    poetry_with_plugins: Poetry, io: BufferedIO, debug_out: bool
) -> None:
    io.set_verbosity(Verbosity.DEBUG if debug_out else Verbosity.NORMAL)
    poetry_with_plugins.local_config["self"]["plugins"] = {
        "irrelevant": {"version": "1.0", "markers": "python_version < '3'"}
    }
    cache = ProjectPluginCache(poetry_with_plugins, io)

    cache.ensure_plugins()

    assert cache._config_file.exists()
    assert io.fetch_output() == (
        "No relevant project plugins for Poetry's environment defined.\n\n"
        if debug_out
        else ""
    )
    assert io.fetch_error() == ""


def test_ensure_plugins_remove_outdated(
    poetry_with_plugins: Poetry, io: BufferedIO, fixture_dir: FixtureDirGetter
) -> None:
    # Test with irrelevant plugins because this is the first return
    # where it is relevant that an existing cache is removed.
    poetry_with_plugins.local_config["self"]["plugins"] = {
        "irrelevant": {"version": "1.0", "markers": "python_version < '3'"}
    }
    fixture_path = fixture_dir("project_plugins")
    cache = ProjectPluginCache(poetry_with_plugins, io)
    cache._path.mkdir(parents=True)
    dist_info = "my_application_plugin-1.0.dist-info"
    shutil.copytree(fixture_path / dist_info, cache._path / dist_info)
    cache._config_file.touch()

    cache.ensure_plugins()

    assert cache._config_file.exists()
    assert not (cache._path / dist_info).exists()
    assert io.fetch_output() == (
        "Removing the project's plugin cache because it is outdated\n"
    )
    assert io.fetch_error() == ""


def test_ensure_plugins_ignore_already_installed_in_system_env(
    poetry_with_plugins: Poetry,
    io: BufferedIO,
    system_env: Env,
    fixture_dir: FixtureDirGetter,
) -> None:
    fixture_path = fixture_dir("project_plugins")
    for dist_info in (
        "my_application_plugin-2.0.dist-info",
        "my_other_plugin-1.0.dist-info",
    ):
        shutil.copytree(fixture_path / dist_info, system_env.purelib / dist_info)
    cache = ProjectPluginCache(poetry_with_plugins, io)

    cache.ensure_plugins()

    assert cache._config_file.exists()
    assert io.fetch_output() == (
        "Ensuring that the Poetry plugins required by the project are available...\n"
        "All required plugins have already been installed in Poetry's environment.\n\n"
    )
    assert io.fetch_error() == ""


def test_ensure_plugins_install_missing_plugins(
    poetry_with_plugins: Poetry,
    io: BufferedIO,
    system_env: Env,
    fixture_dir: FixtureDirGetter,
    mocker: MockerFixture,
) -> None:
    cache = ProjectPluginCache(poetry_with_plugins, io)
    install_mock = mocker.patch.object(cache, "_install")

    cache.ensure_plugins()

    install_mock.assert_called_once_with(
        [
            Dependency("my-application-plugin", ">=2.0"),
            Dependency("my-other-plugin", ">=1.0"),
        ],
        system_env,
        [],
    )
    assert cache._config_file.exists()
    assert io.fetch_output() == (
        "Ensuring that the Poetry plugins required by the project are available...\n"
        "The following Poetry plugins are required by the project"
        " but are not installed in Poetry's environment:\n"
        "  - my-application-plugin (>=2.0)\n"
        "  - my-other-plugin (>=1.0)\n"
        "Installing Poetry plugins only for the current project...\n\n"
    )
    assert io.fetch_error() == ""


def test_ensure_plugins_install_only_missing_plugins(
    poetry_with_plugins: Poetry,
    io: BufferedIO,
    system_env: Env,
    fixture_dir: FixtureDirGetter,
    mocker: MockerFixture,
) -> None:
    fixture_path = fixture_dir("project_plugins")
    dist_info = "my_application_plugin-2.0.dist-info"
    shutil.copytree(fixture_path / dist_info, system_env.purelib / dist_info)
    cache = ProjectPluginCache(poetry_with_plugins, io)
    install_mock = mocker.patch.object(cache, "_install")

    cache.ensure_plugins()

    install_mock.assert_called_once_with(
        [Dependency("my-other-plugin", ">=1.0")],
        system_env,
        [Package("my-application-plugin", "2.0")],
    )
    assert cache._config_file.exists()
    assert io.fetch_output() == (
        "Ensuring that the Poetry plugins required by the project are available...\n"
        "The following Poetry plugins are required by the project"
        " but are not installed in Poetry's environment:\n"
        "  - my-other-plugin (>=1.0)\n"
        "Installing Poetry plugins only for the current project...\n\n"
    )
    assert io.fetch_error() == ""


@pytest.mark.parametrize("debug_out", [False, True])
def test_ensure_plugins_install_overwrite_wrong_version_plugins(
    poetry_with_plugins: Poetry,
    io: BufferedIO,
    system_env: Env,
    fixture_dir: FixtureDirGetter,
    mocker: MockerFixture,
    debug_out: bool,
) -> None:
    io.set_verbosity(Verbosity.DEBUG if debug_out else Verbosity.NORMAL)
    fixture_path = fixture_dir("project_plugins")
    dist_info = "my_application_plugin-1.0.dist-info"
    shutil.copytree(fixture_path / dist_info, system_env.purelib / dist_info)
    cache = ProjectPluginCache(poetry_with_plugins, io)
    install_mock = mocker.patch.object(cache, "_install")

    cache.ensure_plugins()

    install_mock.assert_called_once_with(
        [
            Dependency("my-application-plugin", ">=2.0"),
            Dependency("my-other-plugin", ">=1.0"),
        ],
        system_env,
        [],
    )
    assert cache._config_file.exists()
    start = (
        "Ensuring that the Poetry plugins required by the project are available...\n"
    )
    opt = (
        "The following Poetry plugins are required by the project"
        " but are not satisfied by the installed versions:\n"
        "  - my-application-plugin (>=2.0)\n"
        "    installed: my-application-plugin (1.0)\n"
    )
    end = (
        "The following Poetry plugins are required by the project"
        " but are not installed in Poetry's environment:\n"
        "  - my-application-plugin (>=2.0)\n"
        "  - my-other-plugin (>=1.0)\n"
        "Installing Poetry plugins only for the current project...\n\n"
    )
    expected = (start + opt + end) if debug_out else (start + end)
    assert io.fetch_output() == expected
    assert io.fetch_error() == ""


def test_ensure_plugins_pin_other_installed_packages(
    poetry_with_plugins: Poetry,
    io: BufferedIO,
    system_env: Env,
    fixture_dir: FixtureDirGetter,
    mocker: MockerFixture,
) -> None:
    fixture_path = fixture_dir("project_plugins")
    for dist_info in (
        "my_application_plugin-2.0.dist-info",
        "some_lib-1.0.dist-info",
    ):
        shutil.copytree(fixture_path / dist_info, system_env.purelib / dist_info)
    cache = ProjectPluginCache(poetry_with_plugins, io)
    install_mock = mocker.patch.object(cache, "_install")

    cache.ensure_plugins()

    install_mock.assert_called_once_with(
        [Dependency("my-other-plugin", ">=1.0")],
        system_env,
        [Package("my-application-plugin", "2.0"), Package("some-lib", "1.0")],
    )
    assert cache._config_file.exists()
    assert io.fetch_output() == (
        "Ensuring that the Poetry plugins required by the project are available...\n"
        "The following Poetry plugins are required by the project"
        " but are not installed in Poetry's environment:\n"
        "  - my-other-plugin (>=1.0)\n"
        "Installing Poetry plugins only for the current project...\n\n"
    )
    assert io.fetch_error() == ""
