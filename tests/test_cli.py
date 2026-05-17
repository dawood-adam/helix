def test_setup_creates_config_and_is_idempotent(run, tmp_path):
    r = run("setup", "--model", "anthropic:claude-sonnet-4.6")
    assert r.exit_code == 0, r.output
    assert "Ready." in r.output
    assert (tmp_path / "home" / "models.toml").exists()
    assert (tmp_path / "home" / "atlas" / "ATLAS.md").exists()
    again = run("setup")
    assert "Already set up" in again.output


def test_setup_fails_closed_on_bad_model(run, tmp_path):
    r = run("setup", "--model", "not-a-ref")
    assert r.exit_code != 0
    assert "nothing was changed" in r.output
    assert not (tmp_path / "home" / "models.toml").exists()


def test_queue_before_setup_nudges(run):
    r = run()
    assert r.exit_code == 0
    assert "isn't set up" in r.output


def test_first_run_screen_is_the_A2_contract(ready_run):
    r = ready_run()
    assert "Nothing needs you yet." in r.output
    assert 'helix think' in r.output
    assert "NEEDS YOU NOW" not in r.output            # badge is zero


def test_init_creates_project_with_snapshot_and_lists_it(ready_run):
    r = ready_run("init", "bowel-length")
    assert r.exit_code == 0, r.output
    assert "rung 'notes'" in r.output
    assert "snap:bowel-length@1" in r.output
    home = ready_run()
    assert "bowel-length" in home.output
    assert "[notes]" in home.output                   # plain-language


def test_project_fallback_dispatch(ready_run):
    ready_run("init", "bl")
    r = ready_run("bl")                                # helix <project>
    assert r.exit_code == 0
    assert "nothing is blocked on you" in r.output


def test_unknown_project_is_helpful(ready_run):
    r = ready_run("nope")
    assert r.exit_code != 0
    assert "no such project" in r.output and "helix init" in r.output


def test_lifecycle_cli_uses_plain_language(ready_run):
    ready_run("init", "bl")
    up = ready_run("promote", "bl")
    assert "'project'" in up.output                   # not 'active'
    up2 = ready_run("promote", "bl")
    assert "'published'" in up2.output
    top = ready_run("promote", "bl")
    assert top.exit_code != 0 and "top" in top.output
    dn = ready_run("demote", "bl")
    assert "'project'" in dn.output
    ar = ready_run("archive", "bl")
    assert "archived" in ar.output


def test_why_renders_decision_and_bullets(ready_run):
    ready_run("init", "bl")
    r = ready_run("why", "bl")
    assert r.exit_code == 0
    assert "Decision 1" in r.output
    assert "Why (one-tap summary):" in r.output
    bad = ready_run("why", "bl#decision-99")
    assert bad.exit_code != 0 and "no such decision" in bad.output


def test_undo_logs_a_reversal(ready_run):
    ready_run("init", "bl")
    at_start = ready_run("undo", "bl")
    assert "nothing to undo" in at_start.output
    ready_run("promote", "bl")
    r = ready_run("undo", "bl")
    assert r.exit_code == 0
    assert "reverted to" in r.output


def test_think_is_ticket_free(ready_run, tmp_path):
    r = ready_run("think", "synthetic CT for bowel length")
    assert r.exit_code == 0
    assert "ticket-free" in r.output
    assert "created no queue item" in r.output
    # No project, no queue item.
    home = ready_run()
    assert "Nothing needs you yet." in home.output
    assert "Your projects:" not in home.output


def test_think_then_init_from_think_seeds(ready_run):
    ready_run("think", "bowel length idea")
    r = ready_run("init", "bowel-length", "--from-think")
    assert "seeded from Think" in r.output


FAKE = {"HELIX_EXPLORE_BACKEND": "fake"}
FAIL = {"HELIX_EXPLORE_BACKEND": "fake-fail"}


def test_explore_runs_and_writes_to_notes(ready_run):
    r = ready_run("explore", "synthetic CT for bowel length", env=FAKE)
    assert r.exit_code == 0, r.output
    assert "Explore done" in r.output
    assert "papers → Notes" in r.output
    assert "Ticket-free" in r.output                 # §9.10: no gate
    assert "helix init <name> --from-think" in r.output


def test_explore_result_surfaces_as_fyi_then_consumed(ready_run):
    ready_run("explore", "bowel length", env=FAKE)
    home = ready_run()
    assert "FYI" in home.output
    assert "Explore done" in home.output
    assert "NEEDS YOU NOW" not in home.output        # FYI, never a gate
    # 'Make it a project' = init --from-think; that consumes the FYI.
    init = ready_run("init", "bowel-length", "--from-think")
    assert "explore result" in init.output
    after = ready_run()
    assert "Explore done" not in after.output         # consumed
    assert "bowel-length" in after.output


def test_explore_fails_closed_without_faking(ready_run):
    r = ready_run("explore", "anything", env=FAIL)
    assert r.exit_code != 0
    assert "fabricated nothing" in r.output or "No results were" in \
        r.output or "simulated network outage" in r.output
    # Nothing recorded -> no FYI.
    assert "Explore done" not in ready_run().output


def test_explore_model_override(ready_run):
    r = ready_run("explore", "q", "--model", "openai:gpt-5", env=FAKE)
    assert r.exit_code == 0
    assert "model: openai:gpt-5" in r.output


def test_model_list_use_set(ready_run):
    lst = ready_run("model", "list")
    assert "explore" in lst.output and "[default]" in lst.output
    use = ready_run("model", "use", "local:qwen2.5:32b")
    assert "global default" in use.output
    assert "local:qwen2.5:32b" in ready_run("model", "list").output
    st = ready_run("model", "set", "builder", "local:qwen2.5-coder:32b")
    assert "builder" in st.output
    bad = ready_run("model", "use", "bogus")
    assert bad.exit_code != 0


def test_atlas_search_scope_message_and_notes(ready_run):
    ready_run("explore", "centerline tracing bowel length", env=FAKE)
    # Default scope hides scratch (§6.3) — message must be accurate,
    # not the misleading "empty knowledge base".
    default = ready_run("atlas", "search", "centerline tracing")
    assert "hidden by default" in default.output
    assert "--notes" in default.output
    # Explicitly asking includes Notes and returns ranked context.
    withnotes = ready_run("atlas", "search", "centerline tracing",
                          "--notes", "--budget", "1500")
    assert withnotes.exit_code == 0
    assert "tok" in withnotes.output and "src:" in withnotes.output


def test_atlas_lint_reports_and_is_honest(ready_run):
    clean = ready_run("atlas", "lint")
    assert "clean" in clean.output
    ready_run("explore", "bowel length", env=FAKE)
    dirty = ready_run("atlas", "lint")
    assert "orphan" in dirty.output                     # isolated sources
    assert "contradiction lint needs the LLM critic" in dirty.output


AG = {"HELIX_AGENTS": "fake"}


def test_run_then_gate_in_queue_then_resolve(ready_run):
    ready_run("init", "bl")
    r = ready_run("run", "bl", env=AG)
    assert r.exit_code == 0
    assert "Approve the scope?" in r.output            # interrupted at gate
    # The blocking gate is now a real NEEDS-YOU queue item (§9.1).
    q = ready_run()
    assert "NEEDS YOU NOW" in q.output and "bl" in q.output
    assert "Approve the scope?" in q.output
    # `helix bl` with no flags renders the §9.3 gate view + commands.
    view = ready_run("bl", env=AG)
    assert "options:" in view.output and "recommended" in view.output
    assert "helix bl --approve" in view.output
    # Resolve with the recommended option; it advances + soft-commits.
    adv = ready_run("bl", "--approve", env=AG)
    assert "Recorded 'approve'" in adv.output
    assert "helix undo bl` reverts" in adv.output
    assert "Approve the approach?" in adv.output       # next gate


def test_run_blocked_message_when_already_interrupted(ready_run):
    ready_run("init", "bl")
    ready_run("run", "bl", env=AG)
    again = ready_run("run", "bl", env=AG)
    assert "blocked on a gate" in again.output


def test_teach_back_required_on_private_project(ready_run):
    ready_run("init", "secret", "--private")
    ready_run("run", "secret", env=AG)
    # privacy=strict ⇒ teach-back is the deliverable (§9.3): --why required.
    blocked = ready_run("secret", "--approve", env=AG)
    assert blocked.exit_code != 0
    assert "requires teach-back" in blocked.output
    ok = ready_run("secret", "--approve", "--why",
                   "scope is tight and well-evidenced", env=AG)
    assert ok.exit_code == 0 and "Recorded" in ok.output


def test_vc_and_loom_prism_doctor_cli(ready_run, tmp_path):
    ready_run("init", "bl")
    # Build a real DAG through the workflow (offline fake agents).
    ready_run("run", "bl", env={"HELIX_AGENTS": "fake"})
    for _ in range(8):                          # resolve gates to completion
        st = ready_run("bl", "--approve", env={"HELIX_AGENTS": "fake"})
        if "workflow complete" in st.output:
            break
    hist = ready_run("history", "bl")
    assert hist.exit_code == 0 and "decision-" in hist.output
    loom = ready_run("loom", "bl")
    assert loom.exit_code == 0 and "Loom ·" in loom.output
    prism = ready_run("prism", "bl")
    assert "Strategy" in prism.output and "Data" in prism.output
    doc = ready_run("doctor", "bl")
    assert doc.exit_code == 0 and "helix doctor" in doc.output
    le = ready_run("loom", "bl", "--export", str(tmp_path / "l.svg"))
    assert (tmp_path / "l.svg").exists() and "SVG" in le.output


def test_freeze_emits_supplement(ready_run):
    ready_run("init", "bl")
    ready_run("promote", "bl")                  # notes -> project
    out = ready_run("freeze", "bl")
    assert "supplement" in out.output.lower()
    peek = ready_run("peek", "bl")
    assert peek.exit_code == 0


def test_salvage_cli(ready_run):
    ready_run("init", "bl")
    ready_run("run", "bl", env={"HELIX_AGENTS": "fake"})
    # fork a line then salvage it
    from click.testing import CliRunner  # noqa: F401
    ready_run("bl", "--option", "redo_with_focus",
              env={"HELIX_AGENTS": "fake"})
    # use the snapshot store directly is covered by unit tests; here just
    # assert the command rejects an unknown branch cleanly
    bad = ready_run("salvage", "bl", "ghost-branch")
    assert bad.exit_code != 0 and "unknown branch" in bad.output


def test_peek_is_read_only_status(ready_run):
    ready_run("init", "bl")
    r = ready_run("peek", "bl")
    assert r.exit_code == 0
    assert "rung: notes" in r.output
    assert "branch: main" in r.output


def test_config_show_and_set(ready_run):
    r = ready_run("config", "show")
    assert "atlas_root:" in r.output
    s = ready_run("config", "set", "author", "ada")
    assert "set author = ada" in s.output
    assert "author: ada" in ready_run("config", "show").output
