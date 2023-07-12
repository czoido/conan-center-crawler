import os
import sys

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


def get_information_with_conan_install(conan_api, packages_info, parser_failed):
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
                                                             [remote], None)
            conan_api.graph.analyze_binaries(deps_graph, ["missing"], remotes=[remote])

            conan_api.install.install_binaries(deps_graph=deps_graph, remotes=[remote])

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
