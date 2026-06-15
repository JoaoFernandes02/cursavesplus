"""Tools / maintenance tab."""

from __future__ import annotations

import customtkinter as ctk

from ...importer import copy_between_workspaces
from ..runner import CommandRunner
from ..widgets import ChatCheckList, WorkspaceSelector, confirm_action, warn_cursor_running


def build_tools(parent, runner: CommandRunner, log_append, is_enabled: callable) -> None:
    frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    ctk.CTkLabel(frame, text="Maintenance", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(4, 8),
    )

    maint_frame = ctk.CTkFrame(frame, fg_color="transparent")
    maint_frame.pack(fill="x", pady=4)

    def run(args):
        if not is_enabled() and args[0] not in ("doctor", "repair", "migrate"):
            return
        runner.run(CommandRunner.cursaves_argv(*args))

    def doctor_recover():
        if confirm_action("Doctor recover", "Re-register orphaned chats in workspaces?"):
            run(["doctor", "--recover"])

    def migrate():
        if warn_cursor_running("migrate") is False:
            return
        if confirm_action("Migrate", "Migrate chats to Cursor 3.0 global index?"):
            run(["migrate"])

    def purge():
        if warn_cursor_running("purge") is False:
            return
        if confirm_action("Purge", "Delete chats from Cursor DB to free space?"):
            run(["purge"])

    maint_buttons = [
        ("Doctor", lambda: run(["doctor"])),
        ("Doctor recover", doctor_recover),
        ("Repair blobs", lambda: run(["repair"])),
        ("Migrate", migrate),
        ("Migrate dry-run", lambda: run(["migrate", "--dry-run"])),
        ("Purge", purge),
    ]
    row = ctk.CTkFrame(maint_frame, fg_color="transparent")
    row.pack(fill="x")
    for i, (label, cmd) in enumerate(maint_buttons):
        if i > 0 and i % 3 == 0:
            row = ctk.CTkFrame(maint_frame, fg_color="transparent")
            row.pack(fill="x")
        ctk.CTkButton(row, text=label, command=cmd, width=130).pack(side="left", padx=4, pady=4)

    ctk.CTkLabel(frame, text="Delete snapshots", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(12, 4),
    )
    del_frame = ctk.CTkFrame(frame, fg_color="transparent")
    del_frame.pack(fill="x", pady=4)
    del_id = ctk.CTkEntry(del_frame, placeholder_text="Snapshot / composer ID", width=280)
    del_id.pack(side="left", padx=4)
    ws_del = WorkspaceSelector(del_frame, label="")

    def delete_id():
        sid = del_id.get().strip()
        if not sid:
            return
        if confirm_action("Delete", f"Delete snapshot {sid}?"):
            w = ws_del.get_workspace_arg()
            args = ["delete", "--id", sid, "-y"]
            if w:
                args.extend(["-w", w])
            run(args)

    def delete_all_project():
        if confirm_action("Delete all", "Delete all snapshots for this workspace project?"):
            w = ws_del.get_workspace_arg()
            args = ["delete", "--all", "-y"]
            if w:
                args.extend(["-w", w])
            run(args)

    def delete_all_projects():
        if not confirm_action("Delete ALL", "Delete ALL snapshots for ALL projects?"):
            return
        if confirm_action("Confirm", "This cannot be undone. Really delete everything?"):
            run(["delete", "--all-projects", "-y"])

    ctk.CTkButton(del_frame, text="Delete by ID", command=delete_id, width=120).pack(
        side="left", padx=4,
    )
    ctk.CTkButton(del_frame, text="Delete all (project)", command=delete_all_project, width=150).pack(
        side="left", padx=4,
    )
    ctk.CTkButton(del_frame, text="Delete ALL projects", command=delete_all_projects, width=150).pack(
        side="left", padx=4,
    )

    ctk.CTkLabel(frame, text="Copy chats between workspaces", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(12, 4),
    )
    copy_frame = ctk.CTkFrame(frame, fg_color="transparent")
    copy_frame.pack(fill="x", pady=4)

    src_ws = WorkspaceSelector(copy_frame, label="Source workspace")
    tgt_ws = WorkspaceSelector(copy_frame, label="Target workspace")
    chat_list = ChatCheckList(copy_frame)
    force_var = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(copy_frame, text="Force", variable=force_var).pack(anchor="w", padx=4, pady=4)

    def load_chats():
        ws = src_ws.get_workspace()
        if ws:
            chat_list.load(ws["path"], ws["workspace_dir"])

    ctk.CTkButton(copy_frame, text="Load chats from source", command=load_chats, width=180).pack(
        anchor="w", padx=4, pady=4,
    )

    def do_copy():
        source = src_ws.get_workspace()
        target = tgt_ws.get_workspace()
        if not source or not target:
            log_append("Select source and target workspaces.\n")
            return
        if str(source["workspace_dir"]) == str(target["workspace_dir"]):
            log_append("Source and target must be different.\n")
            return
        ids = chat_list.selected_ids()
        if not ids:
            log_append("No chats selected.\n")
            return

        def _copy():
            success, failure = copy_between_workspaces(
                ids,
                source["workspace_dir"],
                target["workspace_dir"],
                source_path=source["path"],
                target_path=target["path"],
                force=force_var.get(),
            )
            print(f"Copy done: {success} succeeded, {failure} failed.")

        runner.run_callable(_copy)

    ctk.CTkButton(copy_frame, text="Copy selected chats", command=do_copy, width=180).pack(
        anchor="w", padx=4, pady=8,
    )
