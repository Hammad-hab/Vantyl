import argparse
import os
import shlex
import subprocess
import xml.etree.ElementTree as ET

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk


DEFAULT_ITEM_ICON = "image-missing"
DEFAULT_FOLDER_ICON = "folder"


CSS = """
window {
    background-color: #202020;
}

* {
    font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
}

.header {
    background-color: #202020;
    border-bottom: 1px solid #2c2c2c;
}

.header-title {
    color: #e8e8e8;
    font-size: 12px;
}

.content {
    background-color: #202020;
}

entry.search-entry {
    background-color: #2b2b2b;
    color: #ffffff;
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    padding: 2px 14px;
    font-size: 14px;
    caret-color: #ffffff;
}

entry.search-entry:focus {
    border-color: #60cdff;
    background-color: #323232;
}

.app-tile {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    transition: background-color 120ms ease;
}

.app-tile:hover {
    background-color: #3b3b3b;
}

.app-tile:active {
    background-color: #454545;
}

.app-label {
    color: #e8e8e8;
    font-size: 12px;
}

.section-label {
    color: #9b9b9b;
    font-size: 13px;
    font-weight: bold;
}

.back-button {
    background-color: transparent;
    background-image: none;
    border: none;
    box-shadow: none;
    color: #e8e8e8;
    font-size: 13px;
    padding: 4px 10px;
    border-radius: 6px;
}

.back-button:hover {
    background-color: #3b3b3b;
}

.empty-label {
    color: #7a7a7a;
    font-size: 13px;
}

scrollbar {
    background-color: #202020;
}

scrollbar slider {
    background-color: #4a4a4a;
    border-radius: 6px;
    min-width: 6px;
}

scrollbar slider:hover {
    background-color: #606060;
}
"""


class MenuNode:
    """A single entry from the menu XML: either a folder (has children)
    or a leaf item (has an exec command)."""

    def __init__(self, name, icon=None, exec_cmd=None, is_folder=False):
        self.name = name
        self.icon = icon or (DEFAULT_FOLDER_ICON if is_folder else DEFAULT_ITEM_ICON)
        self.exec_cmd = exec_cmd
        self.is_folder = is_folder
        self.children = []


def parse_menu_file(path):
    """Parse a menu XML file into a tree of MenuNode.

    Expected format:

        <menu>
            <item name="Firefox" icon="firefox" exec="firefox"/>
            <folder name="System" icon="folder">
                <item name="Settings" icon="preferences-system" exec="..."/>
                <folder name="Advanced">
                    <item name="Terminal" icon="utilities-terminal" exec="xterm"/>
                </folder>
            </folder>
        </menu>

    Folders can nest arbitrarily deep. Unrecognized tags are ignored.
    """

    tree = ET.parse(path)
    xml_root = tree.getroot()

    root_node = MenuNode(name="root", is_folder=True)

    def build(xml_elem, parent_node):
        for child in xml_elem:
            if child.tag == "folder":
                node = MenuNode(
                    name=child.get("name", "Folder"),
                    icon=child.get("icon"),
                    is_folder=True,
                )
                parent_node.children.append(node)
                build(child, node)
            elif child.tag == "item":
                node = MenuNode(
                    name=child.get("name", "App"),
                    icon=child.get("icon"),
                    exec_cmd=child.get("exec"),
                    is_folder=False,
                )
                parent_node.children.append(node)
            # Unknown tags are silently skipped.

    build(xml_root, root_node)
    return root_node


def build_demo_menu():
    """Fallback menu used when no XML file is given (or it can't be read),
    so the launcher still has something to show."""

    root = MenuNode(name="root", is_folder=True)

    top_level = ["Firefox", "Terminal", "Files", "Calculator"]
    for name in top_level:
        root.children.append(MenuNode(name=name, exec_cmd=None))

    internet = MenuNode(name="Internet", is_folder=True)
    internet.children.append(MenuNode(name="Firefox", icon="firefox"))
    internet.children.append(MenuNode(name="Thunderbird", icon="thunderbird"))
    root.children.append(internet)

    system = MenuNode(name="System", is_folder=True)
    system.children.append(MenuNode(name="Settings", icon="preferences-system"))
    advanced = MenuNode(name="Advanced", is_folder=True)
    advanced.children.append(MenuNode(name="Terminal", icon="utilities-terminal"))
    system.children.append(advanced)
    root.children.append(system)

    return root


def parse_args():
    parser = argparse.ArgumentParser(description="Vantum app launcher")
    parser.add_argument(
        "menu_file",
        nargs="?",
        default=None,
        help="Path to a menu XML file describing folders and items",
    )
    return parser.parse_args()


class AppTile(Gtk.EventBox):
    def __init__(self, node, on_activate):
        super().__init__()

        # Real GdkWindow needed for the CSS background/border/hover to paint.
        self.set_visible_window(True)
        self.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
        )

        self.node = node
        self.on_activate = on_activate
        self.get_style_context().add_class("app-tile")
        self.connect("button-press-event", self._on_click)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8
        )
        box.set_border_width(14)
        self.add(box)

        icon_name = node.icon or (
            DEFAULT_FOLDER_ICON if node.is_folder else DEFAULT_ITEM_ICON
        )
        icon_theme = Gtk.IconTheme.get_default()
        if not icon_theme.has_icon(icon_name):
            icon_name = DEFAULT_FOLDER_ICON if node.is_folder else DEFAULT_ITEM_ICON

        image = Gtk.Image.new_from_icon_name(
            icon_name,
            Gtk.IconSize.DIALOG
        )
        image.set_pixel_size(48)
        image.set_halign(Gtk.Align.CENTER)

        label = Gtk.Label(label=node.name)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_line_wrap(True)
        label.set_max_width_chars(12)
        label.get_style_context().add_class("app-label")

        box.pack_start(image, False, False, 0)
        box.pack_start(label, False, False, 0)

    def _on_click(self, widget, event):
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.on_activate(self.node)


class MainWindow(Gtk.Window):

    def __init__(self, menu_root):
        super().__init__()

        self.set_title("Vantum")
        self.set_default_size(900, 620)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_decorated(False)

        self.menu_root = menu_root
        self.path_stack = []
        self.current = self.menu_root

        self.load_css()

        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL
        )
        self.add(root)

        self.build_header(root)
        self.build_content(root)

    def load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def build_header(self, parent):

        header = Gtk.EventBox()
        header.set_size_request(-1, 40)
        header.get_style_context().add_class("header")

        parent.pack_start(header, False, False, 0)

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10
        )
        box.set_border_width(8)
        header.add(box)

        title = Gtk.Label(label="Vantum")
        title.get_style_context().add_class("header-title")

        box.pack_start(title, False, False, 0)

        header.connect(
            "button-press-event",
            self.begin_move
        )

    def build_content(self, parent):

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18
        )
        content.set_border_width(24)
        content.get_style_context().add_class("content")

        parent.pack_start(content, True, True, 0)

        # Centered, width-limited search box, Win11 start-menu style.
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_row.set_halign(Gtk.Align.CENTER)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search applications...")
        self.search.set_size_request(480, -1)
        self.search.get_style_context().add_class("search-entry")
        self.search.connect("search-changed", self.on_search_changed)
        self.search.connect("changed", self.on_search_changed)

        search_row.pack_start(self.search, False, False, 0)
        content.pack_start(search_row, False, False, 0)

        # Breadcrumb / back-navigation row.
        nav_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.back_button = Gtk.Button(label="\u2039 Back")
        self.back_button.set_relief(Gtk.ReliefStyle.NONE)
        self.back_button.get_style_context().add_class("back-button")
        self.back_button.connect("clicked", lambda *_: self.go_back())
        nav_row.pack_start(self.back_button, False, False, 0)

        self.section_label = Gtk.Label(label="All apps")
        self.section_label.set_halign(Gtk.Align.START)
        self.section_label.get_style_context().add_class("section-label")
        nav_row.pack_start(self.section_label, False, False, 0)

        content.pack_start(nav_row, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC
        )

        content.pack_start(scrolled, True, True, 0)

        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(6)
        flow.set_min_children_per_line(2)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_row_spacing(12)
        flow.set_column_spacing(12)
        flow.set_homogeneous(True)
        flow.set_halign(Gtk.Align.CENTER)
        flow.set_valign(Gtk.Align.START)

        scrolled.add(flow)

        self.flow = flow

        # Fallback label shown when a folder is empty or a search matches nothing.
        self.empty_label = Gtk.Label(label="No apps found")
        self.empty_label.get_style_context().add_class("empty-label")
        self.empty_label.set_no_show_all(True)
        content.pack_start(self.empty_label, False, False, 0)

        self.refresh_view()

    # -- menu tree navigation -------------------------------------------------

    def flatten(self, node):
        """Yield every leaf item under node, recursing into folders."""
        for child in node.children:
            if child.is_folder:
                yield from self.flatten(child)
            else:
                yield child

    def refresh_view(self):
        query = self.search.get_text().strip().lower()

        if query:
            nodes = [n for n in self.flatten(self.menu_root) if query in n.name.lower()]
            self.section_label.set_text("Search results")
            self.set_back_enabled(False)
        else:
            nodes = self.current.children
            at_root = self.current is self.menu_root
            self.section_label.set_text("All apps" if at_root else self.current.name)
            self.set_back_enabled(not at_root)

        self.populate_tiles(nodes)

    def set_back_enabled(self, enabled):
        # Fade + disable rather than hide/show: a hidden widget collapses
        # to zero width in the box, which shifts section_label sideways
        # every time you enter/leave a folder. Keeping it always laid out
        # (just invisible and non-interactive) keeps the label's position
        # fixed.
        self.back_button.set_sensitive(enabled)
        self.back_button.set_opacity(1.0 if enabled else 0.0)

    def populate_tiles(self, nodes):
        for child in list(self.flow.get_children()):
            self.flow.remove(child)

        for node in nodes:
            tile = AppTile(node, self.on_tile_activate)
            self.flow.add(tile)

        self.flow.show_all()
        self.empty_label.set_visible(len(nodes) == 0)

    def on_tile_activate(self, node):
        if node.is_folder:
            self.enter_folder(node)
        elif node.exec_cmd:
            self.launch(node.exec_cmd)

    def enter_folder(self, node):
        self.path_stack.append(self.current)
        self.current = node
        self.search.set_text("")
        self.refresh_view()

    def go_back(self):
        if self.path_stack:
            self.current = self.path_stack.pop()
            self.refresh_view()

    def launch(self, exec_cmd):
        try:
            subprocess.Popen(shlex.split(exec_cmd))
        except Exception as exc:
            print(f"Failed to launch '{exec_cmd}': {exc}")

    def on_search_changed(self, entry):
        self.refresh_view()

    def begin_move(self, widget, event):

        if event.button == 1:
            self.begin_move_drag(
                event.button,
                int(event.x_root),
                int(event.y_root),
                event.time
            )


def main():
    args = parse_args()

    if args.menu_file and os.path.isfile(args.menu_file):
        menu_root = parse_menu_file(args.menu_file)
    else:
        if args.menu_file:
            print(f"Menu file '{args.menu_file}' not found, using built-in demo menu.")
        menu_root = build_demo_menu()

    win = MainWindow(menu_root)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()

    Gtk.main()


if __name__ == "__main__":
    main()