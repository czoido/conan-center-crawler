import json
import os
import sys

import yaml
from conan.api.conan_api import ConanAPI
from conan.api.model import ListPattern
from conans.errors import ConanException

from conan_helper import get_information_with_conan_install, get_basic_info_with_inspect
from recipe_parser import get_package_info_from_recipe, get_basic_info_with_parser

force_install_packages = ["boost"]

packages_info = {}

conan_api = ConanAPI()


def parse_repo():
    fail = force_install_packages
    root_dir = '../tmp/conan-center-index/recipes'
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if 'config.yml' in filenames:
            unique_folders = set()
            recipe_name = os.path.basename(dirpath)

            with open(os.path.join(dirpath, 'config.yml'), 'r') as f:
                data = yaml.safe_load(f)

            for version_info in data['versions'].values():
                unique_folders.add(version_info['folder'])

            recipe_folder = 'all'
            if 'all' not in unique_folders:
                # this is not perfect but good enough, order aplphabetically
                sorted_folders = sorted(unique_folders, reverse=True)
                recipe_folder = sorted_folders[0]

            recipe_path = os.path.join(dirpath, recipe_folder, "conanfile.py")

            with open(recipe_path, 'r') as f:
                recipe_content = f.read()

            packages_info[recipe_name] = {}

            try:
                basic_info = get_basic_info_with_inspect(conan_api, recipe_path)
                packages_info[recipe_name].update(basic_info)
            except ConanException as exc:
                basic_info = get_basic_info_with_parser(recipe_name, recipe_content)
                packages_info[recipe_name].update(basic_info)

            try:
                if recipe_name not in force_install_packages:
                    info = get_package_info_from_recipe(recipe_content)
                    if info:
                        packages_info[recipe_name].update(info)
                else:
                    print(f"forcing: {recipe_name} {str(exc)}", file=sys.stderr)
            except Exception as exc:
                print(f"fail: {recipe_name} {str(exc)}", file=sys.stderr)
                fail.append(recipe_name)
    return fail


def main():
    failed = parse_repo()

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

    failed_again = get_information_with_conan_install(conan_api, packages_info, failed)

    json_data = json.dumps({"libraries": packages_info}, indent=4)

    print(json_data, file=sys.stdout)

    print("####################", file=sys.stderr)
    print("Total failures:", len(failed_again), failed_again, file=sys.stderr)
    print("####################", file=sys.stderr)

    return


if __name__ == '__main__':
    main()
