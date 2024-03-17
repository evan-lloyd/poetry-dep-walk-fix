from __future__ import annotations

from poetry.core.packages.dependency import Dependency
from poetry.core.packages.package import Package
from poetry.core.packages.project_package import ProjectPackage

from poetry.puzzle.solver import PackageNode
from poetry.puzzle.solver import aggregate_package_nodes
from poetry.puzzle.solver import calculate_markers
from poetry.puzzle.solver import depth_first_search


def dep(name: str, marker: str) -> Dependency:
    d = Dependency(name, "1")
    d.marker = marker  # type: ignore[assignment]
    return d


def test_dfs() -> None:
    root = ProjectPackage("root", "1")
    a = Package("a", "1")
    b = Package("b", "1")
    c = Package("c", "1")
    packages = [root, a, b, c]
    root.add_dependency(Dependency("a", "1"))
    root.add_dependency(Dependency("b", "1"))
    a.add_dependency(Dependency("b", "1"))
    b.add_dependency(Dependency("a", "1"))
    a.add_dependency(Dependency("c", "1"))
    result, __ = depth_first_search(PackageNode(root, packages))
    depths = {nodes[0].name: [node.depth for node in nodes] for nodes in result}
    assert not depths


def test_dfs_propagate() -> None:
    root = ProjectPackage("root", "1")
    a = Package("a", "1")
    b = Package("b", "1")
    c = Package("c", "1")
    d = Package("d", "1")
    e = Package("e", "1")
    packages = [root, a, b, c, d, e]
    root.add_dependency(dep("a", 'sys_platform == "win32"'))
    root.add_dependency(dep("b", 'sys_platform == "linux"'))
    a.add_dependency(dep("c", 'python_version == "3.8"'))
    b.add_dependency(dep("d", 'python_version == "3.9"'))
    a.add_dependency(dep("e", 'python_version == "3.10"'))
    b.add_dependency(dep("e", 'python_version == "3.11"'))
    combined_nodes, markers = depth_first_search(PackageNode(root, packages))
    results = dict(aggregate_package_nodes(nodes) for nodes in combined_nodes)
    calculate_markers(results, markers)
    assert str(results[root].transitive_marker) == ""
    assert str(results[a].transitive_marker) == 'sys_platform == "win32"'
    assert str(results[b].transitive_marker) == 'sys_platform == "linux"'
    assert (
        str(results[c].transitive_marker)
        == 'sys_platform == "win32" and python_version == "3.8"'
    )
    assert (
        str(results[d].transitive_marker)
        == 'sys_platform == "linux" and python_version == "3.9"'
    )
    assert str(results[e].transitive_marker) == (
        'sys_platform == "win32" and python_version == "3.10"'
        ' or sys_platform == "linux" and python_version == "3.11"'
    )


# TODO: root extras
# TODO: dep with extras
# TODO: loops
# TODO: overrides
