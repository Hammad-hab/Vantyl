import os
import re
import argparse
import configparser
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

OUTPUT_PATH = "menu.xml"

FIELD_CODE_RE = re.compile(r"%[fFuUdDnNickvm]")

# Categories we ignore entirely when picking a folder name -- these are
# generic/qualifier tags in the spec, not something a user would want
# as a menu folder on their own (e.g. an app tagged only "GTK;Utility;"
# should fall under "Utility", not "GTK").
CATEGORY_SKIP = {"GTK", "GNOME", "KDE", "Qt", "X11", "Application"}


def clean_exec(exec_str):
    """Strip .desktop field codes (%f, %U, etc.) — they're meant to be
    substituted with file paths/URIs at launch time, not passed through
    literally to subprocess/shlex."""
    if not exec_str:
        return None
    return FIELD_CODE_RE.sub("", exec_str).strip()


def category_to_folder_name(category):
    """Turn a raw Categories token into a folder name.

    - 'X-<whatever>' -> strip the 'X-' vendor-prefix, keep the rest.
    - anything else -> used as-is.
    In both cases, '-' becomes a space (e.g. 'X-Desktop' -> 'Desktop',
    a hypothetical 'Network-Tools' -> 'Network Tools').
    """
    cat = category.strip()
    if cat.startswith("X-"):
        cat = cat[2:]
    return cat.replace("-", " ").strip()


def pick_folder_name(categories_str):
    """Pick the first usable category from a raw 'Categories=' value and
    convert it to a folder name. Returns None if there's nothing usable
    (missing field, or only skip-listed/empty tokens) -- callers should
    treat that as 'no folder, goes at menu root'."""
    if not categories_str:
        return None

    for token in categories_str.split(";"):
        token = token.strip()
        if not token or token in CATEGORY_SKIP:
            continue
        return category_to_folder_name(token)

    return None


def collect_apps(applications_dir):
    apps = []

    for item in sorted(os.listdir(applications_dir)):
        if not item.endswith(".desktop"):
            continue

        path = os.path.join(applications_dir, item)
        config = configparser.ConfigParser(interpolation=None)

        try:
            config.read(path)
        except configparser.Error as exc:
            print(f"Skipping '{item}': {exc}")
            continue

        if "Desktop Entry" not in config:
            continue

        entry = config["Desktop Entry"]

        if entry.getboolean("NoDisplay", fallback=False):
            continue
        if entry.getboolean("Hidden", fallback=False):
            continue
        if entry.get("Type", "Application") != "Application":
            continue

        name = entry.get("Name")
        exec_cmd = clean_exec(entry.get("Exec"))
        icon = entry.get("Icon")

        if not name or not exec_cmd:
            continue

        folder = pick_folder_name(entry.get("Categories"))

        apps.append({"name": name, "icon": icon, "exec": exec_cmd, "folder": folder})

    return apps


def build_menu_xml(apps):
    root = ET.Element("menu")

    # folder name -> its <folder> Element, created lazily and in
    # first-seen order so the output is stable and grouped sensibly
    # rather than alphabetically scrambled.
    folder_elems = {}

    for app in apps:
        attrs = {"name": app["name"], "exec": app["exec"]}
        if app["icon"]:
            attrs["icon"] = app["icon"]

        if app["folder"]:
            parent = folder_elems.get(app["folder"])
            if parent is None:
                parent = ET.SubElement(root, "folder", {"name": app["folder"]})
                folder_elems[app["folder"]] = parent
        else:
            parent = root

        ET.SubElement(parent, "item", attrs)

    rough = ET.tostring(root, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="    ")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a Vantum menu.xml from installed .desktop files"
    )
    parser.add_argument(
        "applications_dir",
        nargs="?",
        default="/usr/share/applications",
        help="Directory containing .desktop files (default: /usr/share/applications)",
    )
    parser.add_argument(
        "-o", "--output",
        default=OUTPUT_PATH,
        help=f"Path to write the generated menu XML (default: {OUTPUT_PATH})",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.isdir(args.applications_dir):
        raise SystemExit(f"'{args.applications_dir}' is not a directory")

    apps = collect_apps(args.applications_dir)
    xml_text = build_menu_xml(apps)

    xml_text = "\n".join(
        line for line in xml_text.splitlines() if line.strip()
    )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(xml_text + "\n")

    print(f"Wrote {len(apps)} apps to {args.output}")


if __name__ == "__main__":
    main()