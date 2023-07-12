import os
import sys

from conan.api.model import ListPattern
from conan.cli.printers import print_profiles


def get_basic_info_with_inspect(conan_api, recipe_path):
    info = {}
    conanfile = conan_api.local.inspect(os.path.abspath(recipe_path), None, None)
    conanfile_json = conanfile.serialize()
    info["description"] = conanfile_json.get("description", "").replace("\n", "").replace(
        "  ", "")
    license = conanfile_json.get("license", "")
    info["license"] = [license] if type(license) != list else license
    info["v2"] = True
    return info


def get_package_info_with_install(conan_api, packages_info, parser_failed):

    ref_pattern = ListPattern("*", rrev=None)

    try:
        list_bundle = conan_api.list.select(ref_pattern, package_query=None, remote=conan_api.remotes.get("conancenter"))
    except Exception as e:
        raise e
    else:
        results = list_bundle.serialize()

    # first fill versions information in the package_info dict
    for reference in results:
        name, version = reference.split("/")
        if name in packages_info:
            packages_info[name].setdefault("versions", []).append(version)

    # now, try to get missing information from fail packages
    # calling the Conan API we do a conan install over the last version

    versions_to_try = ", ".join([f"{ref}/{packages_info.get(ref).get('versions')[-1]}" for ref in failed])

    print(f"We could not get info for some packages. Will try installing these versions: {versions_to_try}",
          file=sys.stderr)

    install_fails = []
    for ref in parser_failed:
        try:
            print(f"#################################", file=sys.stderr)
            print(f"Try to get cpp_info for: {ref}", file=sys.stderr)
            print(f"#################################", file=sys.stderr)
            version = packages_info.get(ref).get("versions")[-1]
            requires = f"{ref}/{version}"
            host = conan_api.profiles.get_default_host()
            build = conan_api.profiles.get_default_build()
            profile_build = conan_api.profiles.get_profile(profiles=[build])
            profile_host = conan_api.profiles.get_profile(profiles=[host],
                                                          conf=['tools.system.package_manager:mode=install',
                                                                'tools.system.package_manager:sudo=True'])
            print_profiles(profile_host, profile_build)
            deps_graph = conan_api.graph.load_graph_requires([requires], None,
                                                             profile_host, profile_build, None,
                                                             [conan_api.remotes.get("conancenter")], None)
            conan_api.graph.analyze_binaries(deps_graph, ["missing"], remotes=[conan_api.remotes.get("conancenter")])

            conan_api.install.install_binaries(deps_graph=deps_graph, remotes=[conan_api.remotes.get("conancenter")])

            conan_api.install.install_consumer(deps_graph=deps_graph,
                                               source_folder=os.path.join(os.getcwd(), "tmp"))

            nodes = deps_graph.serialize()["nodes"]

            properties_info = {}

            for id, node_info in nodes.items():
                if requires in node_info.get("ref"):
                    cpp_info = node_info.get("cpp_info")
                    for component_name, component_info in cpp_info.items():
                        properties = component_info.get("properties")
                        if properties:
                            if component_name == "root":
                                properties_info.update(properties)
                            elif not component_name.startswith("_"):
                                if not properties_info.get("components"):
                                    properties_info["components"] = {}
                                properties_info["components"][component_name] = properties
                    break

            if properties_info:
                packages_info[ref].update(properties_info)

        except Exception as e:
            install_fails.append(ref)
    return install_fails
