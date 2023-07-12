import ast
import json
import os
import sys
from collections import OrderedDict

import astunparse
import yaml
from conan.api.conan_api import ConanAPI
from conan.api.model import ListPattern
from conan.cli.printers import print_profiles
from conans.errors import ConanException

fail = []
sucess = []


def parse_recipe_info(conanfile):
    tree = ast.parse(conanfile)
    desc = ""
    lic = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for body_node in node.body:
                if isinstance(body_node, ast.Assign) and len(body_node.targets) == 1:
                    target = body_node.targets[0]
                    if isinstance(target, ast.Name) and target.id == "description":
                        value_node = body_node.value
                        if isinstance(value_node, ast.Str):
                            desc = value_node.s
                    if isinstance(target, ast.Name) and target.id == "license":
                        value_node = body_node.value
                        if isinstance(value_node, ast.Str):
                            lic = value_node.s

    return desc, lic


def get_methods_from_conanfile_derived_class(conanfile):
    root = ast.parse(conanfile)

    info = {}

    for node in ast.walk(root):
        if isinstance(node, ast.ClassDef):
            base_classes = [base.id for base in node.bases if isinstance(base, ast.Name)]
            if 'ConanFile' in base_classes:
                for sub_node in node.body:
                    if isinstance(sub_node, ast.FunctionDef) and sub_node.name == "package_info":
                        for stmt in sub_node.body:

                            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                                func = stmt.value.func
                                line = astunparse.unparse(stmt)
                                if isinstance(func,
                                              ast.Attribute) and func.attr == 'set_property' and 'cpp_info.components' not in line:
                                    # Check if the function is called on a component
                                    if isinstance(func.value, ast.Attribute) \
                                            and func.value.attr == 'cpp_info' \
                                            and isinstance(func.value.value, ast.Name) \
                                            and func.value.value.id == 'self':

                                        args = stmt.value.args
                                        if len(args) == 2:
                                            if args[0].s == "cmake_file_name" or args[0].s == "cmake_target_name":
                                                if isinstance(args[1], ast.Str):
                                                    info[args[0].s] = str(args[1].s)
                                                else:
                                                    # the target name of file name is defined by a python variable
                                                    # we will have to use conan to get the info
                                                    raise Exception(
                                                        "Target info can't be recovered by parsing the ConanFile")
                                elif 'cpp_info.components' in line and 'set_property' in line:
                                    args = stmt.value.args
                                    if len(args) == 2 and isinstance(args[0], ast.Str) and isinstance(args[1], ast.Str):
                                        component_name = str(astunparse.unparse(func.value.slice)).replace("'",
                                                                                                           "").replace(
                                            '"', '').strip()
                                        if not component_name.startswith("_"):
                                            info["components"] = info.get("components", {})
                                            info["components"][component_name] = info["components"].get(component_name,
                                                                                                        {})
                                            if args[0].s == "cmake_target_name":
                                                info["components"][component_name]["cmake_target_name"] = args[1].s

    return info


root_dir = 'tmp/conan-center-index/recipes'

packages_info = {}
#
conan_api = ConanAPI()

for dirpath, dirnames, filenames in os.walk(root_dir):
    if 'config.yml' in filenames:
        unique_folders = set()
        recipe_name = os.path.basename(dirpath)
        with open(os.path.join(dirpath, 'config.yml'), 'r') as f:
            data = yaml.safe_load(f)

        for version_info in data['versions'].values():
            unique_folders.add(version_info['folder'])

        recipe_folder = 'all'
        if not 'all' in unique_folders:
            # this is not perfect but good enough, order aplphabetically
            sorted_folders = sorted(unique_folders, reverse=True)
            recipe_folder = sorted_folders[0]

        recipe_path = os.path.join(dirpath, recipe_folder, "conanfile.py")

        if not os.path.exists(recipe_path):
            raise Exception(recipe_path)
        else:
            with open(recipe_path, 'r') as f:
                content = f.read()

        packages_info[recipe_name] = {}

        try:
            conanfile = conan_api.local.inspect(os.path.abspath(recipe_path), None, None)
            conanfile_json = conanfile.serialize()
            packages_info[recipe_name]["description"] = conanfile_json.get("description", "").replace("\n", "").replace(
                "  ", "")
            license = conanfile_json.get("license", "")
            packages_info[recipe_name]["license"] = [license] if type(license) != list else license
            packages_info[recipe_name]["v2"] = True
        except ConanException as exc:
            description, license = parse_recipe_info(content)
            if not description:
                raise exc
            packages_info[recipe_name]["description"] = description.replace("\n", "").replace("  ", "")
            packages_info[recipe_name]["license"] = [license] if type(license) != list else license
            packages_info[recipe_name]["v2"] = False

        try:
            info = get_methods_from_conanfile_derived_class(content)
            if info:
                packages_info[recipe_name].update(info)
            sucess.append(recipe_name)
        except Exception as exc:
            print(f"fail: {recipe_name} {str(exc)}", file=sys.stderr)
            fail.append(recipe_name)

ref_pattern = ListPattern("*", rrev=None)

remote = conan_api.remotes.get("conancenter")

results = OrderedDict()

try:
    list_bundle = conan_api.list.select(ref_pattern, package_query=None, remote=remote)
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

versions_to_try = ", ".join([f"{ref}/{packages_info.get(ref).get('versions')[-1]}" for ref in fail])

print(f"We could not get info for some packages. Will try installing these versions: {versions_to_try}", file=sys.stderr)

failed_again = []

for failed_ref in fail:
    try:
        print(f"#################################", file=sys.stderr)
        print(f"Try to get cpp_info for: {failed_ref}", file=sys.stderr)
        print(f"#################################", file=sys.stderr)
        version = packages_info.get(failed_ref).get("versions")[-1]
        requires = f"{failed_ref}/{version}"
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
            packages_info[failed_ref].update(properties_info)

    except Exception as e:
        failed_again.append(failed_ref)

json_data = json.dumps({"libraries": packages_info}, indent=4)

print(json_data)

print("####################", file=sys.stderr)
print("Total failures:", len(failed_again), failed_again, file=sys.stderr)
print("Total successes:", len(sucess), file=sys.stderr)
print("####################", file=sys.stderr)
