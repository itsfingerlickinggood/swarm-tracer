"""Who&When and MAST-Data: the readers (always), and the measured numbers (only where the datasets are downloaded).

The reader tests use small logs written here in each layout. The dataset tests read the downloaded files in a child
`python3 -I` process (isolated: nothing beside the data can be imported) and skip when datasets-ext/ is absent.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

from agenttrace import failure_eval as FE
from agenttrace import model, readers
from agenttrace import readers_failure as RF

ROOT = FE.ROOT
WW_DIR = os.path.join(FE.DATA, "who_and_when")
MAST_FILE = os.path.join(FE.DATA, "mast_data", "MAD_full_dataset.json")
HAS_WW = os.path.isdir(os.path.join(WW_DIR, "Hand-Crafted")) and os.path.isdir(os.path.join(WW_DIR, "Algorithm-Generated"))
HAS_MAST = os.path.isfile(MAST_FILE)
STORIES = os.path.join(ROOT, "docs", "investigations", "stories")


def isolated(*args):
    """Run agenttrace/failure_eval.py in `python3 -I`, away from the repository and the data; its JSON output."""
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "agenttrace", "failure_eval.py"), *args],
                           cwd=tmp, capture_output=True, text=True, timeout=900,
                           env={**os.environ, "SWARM_TRACER_NO_CACHE": "1"})
    if p.returncode != 0:
        raise AssertionError(p.stderr[-2000:])
    return json.loads(p.stdout)


# ---------------------------------------------------------------------------------------------- readers, on logs written here

HAND_CRAFTED = {"history": [
    {"content": "Find the opening hours.", "role": "human"},
    {"content": "Initial plan: ask the web surfer.", "role": "Orchestrator (thought)"},
    {"content": "Please search for the opening hours.", "role": "Orchestrator (-> WebSurfer)"},
    {"content": "I typed the query.", "role": "WebSurfer"},
    {"content": "Please write the answer down.", "role": "Orchestrator (-> Assistant)"},
    {"content": "Open nine to five.", "role": "Assistant"},
    {"content": "Done.", "role": "Orchestrator (termination condition)"}],
    "mistake_agent": "WebSurfer", "mistake_step": "3", "mistake_reason": "typed the wrong query", "question_ID": "q1"}
GROUP_CHAT = {"history": [
    {"content": "Plan the sum.", "role": "assistant", "name": "Maths_Expert"},
    {"content": "exitcode: 0", "role": "user", "name": "Computer_terminal"},
    {"content": "The sum is right.", "role": "user", "name": "Verification_Expert"}],
    "mistake_agent": "Maths_Expert", "mistake_step": "0"}

CHATDEV = """[2025-31-03 19:09:41 INFO] **[Preprocessing]**

**ChatDev Starts** (20250331190941)
[2025-31-03 19:09:41 INFO] System: **[chatting]**
[2025-31-03 19:09:41 INFO] Chief Executive Officer: **[Start Chat]**

We need a design.
[2025-31-03 19:09:51 INFO] HTTP Request: POST https://api.example.test/v1/chat "HTTP/1.1 200 OK"
[2025-31-03 19:09:59 INFO] Chief Product Officer: **Chief Product Officer<->Chief Executive Officer on : DemandAnalysis, turn 0**

An application.
[2025-31-03 19:10:02 INFO] Chief Executive Officer: **Chief Product Officer<->Chief Executive Officer on : DemandAnalysis, turn 0**

Agreed.
"""
METAGPT = """=== MetaGPT Agent Communication Log - Started at 2025-03-31 12:53:42 ===

[2025-03-31 12:53:42] FROM: Human TO: {'<all>'}
ACTION: metagpt.actions.add_requirement.UserRequirement
CONTENT:
Write a word counter.
--------------------------------------------------------------------------------

[2025-03-31 12:54:14] NEW MESSAGES:

SimpleCoder:
def count(text):
    return len(text.split())
--------------------------------------------------------------------------------

[2025-03-31 12:54:30] NEW MESSAGES:

SimpleTester: def test_count(): assert count("a b") == 2
"""
OPENMANUS = """INFO     [root] start
2025-04-01 01:27:44.445 | INFO     | __main__:run_flow:20 - Read prompt from task.txt
2025-04-01 01:27:47.937 | INFO     | app.llm:update_token_count:250 - Token usage: Input=426
2025-04-01 01:27:47.938 | INFO     | app.flow.planning:_create_initial_plan:179 - Plan created
2025-04-01 01:27:50.255 | INFO     | app.agent.toolcall:think:81 - Manus's thoughts: look at the file
2025-04-01 01:27:50.256 | INFO     | app.agent.toolcall:execute_tool:180 - Activating tool: 'str_replace_editor'...
"""
MAGENTIC = """RUN.SH STARTING !#!#
Installing build dependencies: started
---------- user ----------
How tall is the tower?
---------- MagenticOneOrchestrator ----------
Please look it up.
---------- WebSurfer ----------
I typed the question.
FINAL ANSWER: tall
SCENARIO.PY COMPLETE !#!#
RUN.SH COMPLETE !#!#
"""
AG2_DICTS = ("{'content': ['Solve it.', 'Use Python.'], 'role': 'assistant', 'name': 'mathproxyagent'} "
             "{'content': [\"It's 4.\"], 'role': 'user', 'name': 'assistant'}")
AG2_YAML = """instance_id: abc
problem_statement: add two numbers
trajectory:
      content:
            Solve it.
            Use Python.
      role: assistant
      name: mathproxyagent
      content:
            It is 4.
      role: user
      name: assistant
"""
APPWORLD = """
******************** Task 1/2 (t_1)  ********************
Play the next song.
Response from Supervisor Agent
    send_message(app_name='spotify', message='Play the next song')

Code Execution Output

    reply = self.send_message(...)

Entering spotify Agent message loop
    Message to spotify Agent
        Play the next song

    Response from spotify Agent
        print(apis.api_docs.show_api_descriptions(app_name='spotify'))

    Message to spotify Agent
        [{"name": "next_song"}]

    Response from spotify Agent
        apis.spotify.next_song()

    Reply from spotify Agent to Supervisor
        Done.

Exiting Spotify Agent message loop
Response from send_message API
    Done.

Message to Supervisor Agent
    Done.

Response from Supervisor Agent
    apis.supervisor.complete_task()
"""
HYPERAGENT = """instance_id: proj__1
trajectory:
  HyperAgent_proj__1 - INFO - Initialized HyperAgent instance proj__1
  HyperAgent_proj__1 - INFO - Planner's Response: Thought: find the function first.
  HyperAgent_proj__1 - INFO - Inner-Navigator-Assistant's Response: Thought: search the code.
  Action:
  ```python
  print(result)
  ```
  HyperAgent_proj__1 - INFO - Navigator->Planner: The function is in core.py.
  HyperAgent_proj__1 - INFO - Inner-Editor-Assistant's Response: Thought: patch it.
  HyperAgent_proj__1 - INFO - Editor->Planner: Patched.
"""


def mast_row(mas, text, tid=0, **labels):
    ann = {k: 0 for k in RF.MAST_MODES}
    ann.update({k.replace("m", "").replace("_", "."): v for k, v in labels.items()})
    return {"mas_name": mas, "llm_name": "x", "benchmark_name": "y", "trace_id": tid,
            "trace": {"key": f"{mas}_y_x", "index": tid, "trajectory": text}, "mast_annotation": ann}


def brief(rows):
    return [(r["actor"], r["to"], r["kind"]) for r in rows]


class WhoAndWhenReaderTest(unittest.TestCase):
    def test_parse_role(self):
        self.assertEqual(RF.parse_role("Orchestrator (-> WebSurfer)"), ("Orchestrator", "WebSurfer", "instruction"))
        self.assertEqual(RF.parse_role("Orchestrator (thought)"), ("Orchestrator", None, "thought"))
        self.assertEqual(RF.parse_role("Orchestrator (termination condition)"), ("Orchestrator", None, "termination_condition"))
        self.assertEqual(RF.parse_role("WebSurfer"), ("WebSurfer", None, "message"))
        self.assertEqual(RF.parse_role(None), (None, None, "message"))

    def test_hand_crafted_rows_name_the_recipient_and_keep_the_step_numbers(self):
        rows = RF.who_and_when_rows(HAND_CRAFTED, "hc9")
        self.assertEqual([r["id"] for r in rows], [f"hc9:{i}" for i in range(7)])
        self.assertEqual(brief(rows), [("human", None, "message"), ("Orchestrator", None, "thought"),
                                       ("Orchestrator", "WebSurfer", "instruction"), ("WebSurfer", None, "message"),
                                       ("Orchestrator", "Assistant", "instruction"), ("Assistant", None, "message"),
                                       ("Orchestrator", None, "termination_condition")])
        self.assertEqual([r["parent"] for r in rows[:2]], [None, "hc9:0"])
        self.assertTrue(all(r["time"] is None and r["channel"] == "hc9" for r in rows))
        self.assertEqual(RF.logged_messages(rows), [("hc9:2", "Orchestrator", "WebSurfer"), ("hc9:4", "Orchestrator", "Assistant")])

    def test_group_chat_rows_take_the_agent_from_the_name(self):
        rows = RF.who_and_when_rows(GROUP_CHAT, "ag9")
        self.assertEqual(brief(rows), [("Maths_Expert", None, "assistant"), ("Computer_terminal", None, "user"),
                                       ("Verification_Expert", None, "user")])

    def test_truth_is_the_dataset_label(self):
        rows = RF.who_and_when_rows(HAND_CRAFTED, "hc9")
        t = RF.who_and_when_truth(HAND_CRAFTED, rows)
        self.assertEqual((t["mistake_agent"], t["mistake_step"], t["step_actor"], t["steps"]), ("WebSurfer", 3, "WebSurfer", 7))
        self.assertEqual(t["agents"], ["Assistant", "Orchestrator", "WebSurfer", "human"])
        self.assertIsNone(RF.who_and_when_truth({"mistake_step": "soon"})["mistake_step"])

    def test_clock_and_withholding(self):
        rows = RF.who_and_when_rows(HAND_CRAFTED, "hc9")
        timed = RF.clocked(rows)
        self.assertEqual(timed[0]["time"], "2000-01-01T00:00:00+00:00")
        self.assertEqual(timed[3]["time"], "2000-01-01T00:03:00+00:00")
        self.assertIsNone(rows[0]["time"], "the rows given are not changed")
        self.assertEqual(sum(1 for r in RF.withheld(rows) if r["to"]), 0)
        self.assertEqual(sum(1 for r in rows if r["to"]), 2)
        dated = [dict(rows[0], time="2026-01-01T00:00:00+00:00")] + rows[1:]
        self.assertEqual([r["time"] for r in RF.clocked(dated)][:2], ["2026-01-01T00:00:00+00:00", None], "a run with real times is left alone")

    def test_a_raw_hand_crafted_file_loads_with_its_recipients(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "7.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(HAND_CRAFTED, f)
            events = model.load(p)
            self.assertEqual(model.LAST_REPORT["format"], readers.FORMATS["who_and_when"])
        self.assertEqual(len(events), 7)
        self.assertEqual(sorted({e.actor for e in events}), ["Assistant", "Orchestrator", "WebSurfer", "human"])
        self.assertEqual([(e.actor, e.to) for e in events if e.to], [("Orchestrator", "WebSurfer"), ("Orchestrator", "Assistant")])

    def test_an_ordinary_chat_is_still_a_chat(self):
        rows = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}] * 3
        self.assertEqual(readers.detect(rows), "chat")
        self.assertEqual(readers.detect(GROUP_CHAT["history"] * 2), "chat")
        self.assertEqual(readers.detect(HAND_CRAFTED["history"]), "who_and_when")


class MastReaderTest(unittest.TestCase):
    def test_chatdev(self):
        rows, skipped = RF.mast_rows(mast_row("ChatDev", CHATDEV))
        self.assertEqual(brief(rows), [("Chief Executive Officer", None, "start_chat"),
                                       ("Chief Product Officer", "Chief Executive Officer", "chat"),
                                       ("Chief Executive Officer", "Chief Product Officer", "chat")])
        self.assertEqual(skipped, 3)
        self.assertEqual(rows[1]["time"], "2025-03-31T19:09:59+00:00", "ChatDev prints year-day-month")
        self.assertEqual(rows[1]["text"], "[DemandAnalysis, turn 0] An application.")
        self.assertEqual(rows[0]["id"], "ChatDev_y_x_0:0")

    def test_metagpt(self):
        rows, skipped = RF.mast_rows(mast_row("MetaGPT", METAGPT))
        self.assertEqual(brief(rows), [("Human", None, "requirement"), ("SimpleCoder", None, "message"), ("SimpleTester", None, "message")])
        self.assertEqual((rows[0]["text"], rows[0]["time"]), ("Write a word counter.", "2025-03-31T12:53:42+00:00"))
        self.assertEqual(rows[1]["text"], "def count(text):\n    return len(text.split())")
        self.assertEqual(skipped, 0)

    def test_openmanus(self):
        rows, skipped = RF.mast_rows(mast_row("OpenManus", OPENMANUS))
        self.assertEqual([(r["actor"], r["kind"], r["tool"]) for r in rows],
                         [("user", "run_flow", None), ("PlanningFlow", "_create_initial_plan", None), ("Manus", "think", None),
                          ("Manus", "execute_tool", "str_replace_editor")])
        self.assertEqual(skipped, 1, "the token counter is left out")
        self.assertEqual(rows[0]["time"], "2025-04-01T01:27:44.445+00:00")

    def test_magentic(self):
        rows, _ = RF.mast_rows(mast_row("Magentic", MAGENTIC))
        self.assertEqual(brief(rows), [("user", None, "message"), ("MagenticOneOrchestrator", None, "message"), ("WebSurfer", None, "message")])
        self.assertEqual(rows[2]["text"], "I typed the question.\nFINAL ANSWER: tall")
        self.assertTrue(all(r["time"] is None for r in rows))

    def test_ag2_both_layouts(self):
        for text in (AG2_DICTS, AG2_YAML):
            rows, skipped = RF.mast_rows(mast_row("AG2", text))
            self.assertEqual(brief(rows), [("mathproxyagent", None, "assistant"), ("assistant", None, "user")])
            self.assertEqual(rows[0]["text"], "Solve it.\nUse Python.")
            self.assertEqual(skipped, 0)

    def test_ag2_text_is_never_run(self):
        hostile = "{'content': [__import__('os').getcwd()], 'role': 'user', 'name': 'x'}"
        rows, skipped = RF.mast_rows(mast_row("AG2", hostile))
        self.assertEqual(brief(rows), [("x", None, "user")], "read by its tail, as text")
        self.assertIn("__import__", rows[0]["text"])

    def test_appworld(self):
        rows, skipped = RF.mast_rows(mast_row("AppWorld", APPWORLD))
        self.assertEqual(brief(rows), [("Supervisor", None, "response"), ("Supervisor", None, "tool_output"),
                                       ("Supervisor", "spotify", "message"), ("spotify", None, "response"),
                                       ("spotify", None, "tool_output"), ("spotify", None, "response"),
                                       ("spotify", "Supervisor", "reply"), ("Supervisor", None, "tool_output"),
                                       ("Supervisor", None, "response")])
        self.assertEqual(skipped, 3)
        self.assertEqual(rows[2]["text"], "Play the next song")

    def test_hyperagent(self):
        rows, skipped = RF.mast_rows(mast_row("HyperAgent", HYPERAGENT))
        self.assertEqual(brief(rows), [("Planner", None, "response"), ("Navigator", None, "response"), ("Navigator", "Planner", "message"),
                                       ("Editor", None, "response"), ("Editor", "Planner", "message")])
        self.assertEqual(skipped, 1)
        self.assertEqual(rows[2]["text"], "The function is in core.py.")

    def test_unknown_framework_and_missing_text_give_no_rows(self):
        self.assertEqual(RF.mast_rows(mast_row("Unheard", "x")), ([], 0))
        self.assertEqual(RF.mast_rows({"mas_name": "AG2", "trace": None}), ([], 0))

    def test_labels_and_run_ids(self):
        row = mast_row("AG2", AG2_DICTS, tid=7, m1_3=1, m2_6=None)
        lab = RF.mast_labels(row)
        self.assertEqual((lab["1.3"], lab["2.6"], lab["1.1"], len(lab)), (1, None, 0, 14))
        self.assertEqual(RF.mast_run_id(row), "AG2_y_x_7")

    def test_a_raw_file_loads_as_one_trace_with_a_channel_per_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "mad.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump([mast_row("AppWorld", APPWORLD, 0), mast_row("HyperAgent", HYPERAGENT, 0), mast_row("AppWorld", APPWORLD, 0)], f)
            events = model.load(p)
            self.assertEqual(model.LAST_REPORT["format"], readers.FORMATS["mast"])
            runs = RF.load_mast(p)
        self.assertEqual(len(events), 9 + 5 + 9)
        self.assertEqual(len({e.id for e in events}), 23)
        self.assertEqual([r["run"] for r in runs], ["AppWorld_y_x_0", "HyperAgent_y_x_0", "AppWorld_y_x_0_2"], "a repeated key and id get a suffix")
        self.assertEqual(sorted({e.channel for e in events}), ["AppWorld_y_x_0", "AppWorld_y_x_0_2", "HyperAgent_y_x_0"])
        self.assertEqual(sum(1 for e in events if e.to), 2 + 2 + 2)


# ---------------------------------------------------------------------------------------------- scoring, on made-up counts

class ScoringTest(unittest.TestCase):
    def test_link_counts(self):
        logged = [("r:2", "O", "W"), ("r:4", "O", "A"), ("r:6", "O", "W")]
        tool = [("r:2", "O", "W"), ("r:4", "O", "W"), ("r:3", "W", "O"), ("r:0", "H", "O")]
        c = FE.link_counts(logged, tool)
        self.assertEqual(c, {"logged": 3, "found": 1, "readers_named": 2, "readers_right": 1, "pairs_logged": 2, "pairs_tool": 3,
                             "pairs_both": 1, "pairs_either_way": 2})
        t = FE.link_table([c, FE.link_counts(logged, [])])
        self.assertEqual((t["message_recall"]["k"], t["message_recall"]["n"], t["message_recall"]["share"]), (1, 6, 0.1667))
        self.assertEqual((t["pair_recall"]["k"], t["pair_recall"]["n"]), (1, 4))
        self.assertEqual(t["per_run_message_recall"], {"min": 0.0, "median": 0.333, "max": 0.333, "runs_at_zero": 1})

    def test_rate_carries_its_interval(self):
        r = FE.rate(54, 184)
        self.assertEqual((r["share"], r["ci95"]), (0.2935, [0.232, 0.363]))
        self.assertEqual(FE.rate(0, 0), {"k": 0, "n": 0, "share": None, "ci95": None})

    def test_attribution_scores_each_rule_against_the_label(self):
        rows = RF.who_and_when_rows(HAND_CRAFTED, "hc9")
        run = {"run": "hc9", "subset": "Hand-Crafted", "rows": rows, "truth": RF.who_and_when_truth(HAND_CRAFTED, rows)}
        a = FE.attribution_row(run, {"first_sign": ("hc9:3", "WebSurfer", "message"), "first_harm": None})
        self.assertEqual(a["preds"]["tool_first_sign"], {"agent": "WebSurfer", "step": 3, "agent_right": True, "step_right": True})
        self.assertIsNone(a["preds"]["tool_first_harm"])
        self.assertEqual(a["preds"]["baseline_busiest_agent"]["agent"], "Orchestrator")
        self.assertEqual((a["preds"]["baseline_last_step"]["step"], a["preds"]["baseline_first_step"]["agent"]), (6, "human"))
        t = FE.attribution_table([a])
        self.assertEqual(t["methods"]["tool_first_sign"]["step"]["k"], 1)
        self.assertEqual(t["methods"]["tool_first_harm"]["names_someone"]["k"], 0, "no flag in the run is a miss, not a skip")
        self.assertEqual(t["methods"]["tool_first_harm"]["agent"]["n"], 1)
        self.assertEqual(t["chance"]["agent"], 0.25)
        self.assertEqual(t["chance"]["step"], round(1 / 7, 4))

    def test_one_run_through_the_tool(self):
        rows = RF.who_and_when_rows(HAND_CRAFTED, "hc9")
        undated = FE.measure(rows, "hc9")
        self.assertFalse(undated["dated"])
        self.assertEqual((len(undated["direct"]), undated["direct_undated"]), (0, 2), "without times a logged message is held, not graphed")
        timed = FE.measure(RF.clocked(rows), "hc9")
        self.assertTrue(timed["dated"])
        self.assertEqual(sorted(timed["direct"]), [("hc9:2", "Orchestrator", "WebSurfer"), ("hc9:4", "Orchestrator", "Assistant")])
        self.assertEqual(FE.link_counts(RF.logged_messages(rows), timed["direct"])["found"], 2)
        self.assertEqual(FE.step_of("hc9:12"), 12)


# ---------------------------------------------------------------------------------------------- the downloaded datasets

def saved_or_skip(test, name):
    res = FE.saved(name)
    if res is None:
        test.skipTest(f"reports/external/{name}/results.json is not here")
    return res


def same_tool_or_skip(test, res):
    if res["tool_files"] != FE.tool_state():
        changed = sorted(k for k, v in FE.tool_state().items() if res["tool_files"].get(k) != v)
        test.skipTest("the tool changed since the measurement (" + ", ".join(changed) + "); re-run python3 -I agenttrace/failure_eval.py")


@unittest.skipUnless(HAS_WW, "datasets-ext/who_and_when is not downloaded")
class WhoAndWhenDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = isolated("counts", "who_and_when")

    def test_what_the_reader_loads(self):
        c = self.counts
        self.assertEqual((c["runs"], c["records"], c["addressed"], c["actors"], c["timed"]), (184, 4092, 689, 197, 0))
        self.assertEqual(c["by_subset"], {"Algorithm-Generated": [126, 1099], "Hand-Crafted": [58, 2993]})
        self.assertEqual(c["label_step_is_by_label_agent"], 178)
        self.assertEqual(c["hc1_label"], ["WebSurfer", 12])

    def test_a_raw_file_loads_through_the_tool(self):
        raw = self.counts["raw_file"]
        self.assertEqual(raw["format"], readers.FORMATS["who_and_when"])
        self.assertEqual((raw["records"], raw["addressed"], raw["actors"]), (29, 7, ["Orchestrator", "WebSurfer", "human"]))

    def test_saved_results_agree_with_the_reader(self):
        res = saved_or_skip(self, "who_and_when")
        self.assertEqual(res["totals"], {"runs": 184, "records": 4092, "records_with_time": 0, "logged_messages_with_recipient": 689})
        self.assertEqual(res["label_check"]["label_step_is_by_label_agent"], 178)
        self.assertEqual(res["revision"], "1bcbbd96ba563400cededae6189833b8ea59dcae")
        hc = res["groups"]["Hand-Crafted"]
        self.assertEqual(hc["as_logged"]["runs_dated"], 0)
        self.assertEqual((hc["as_logged"]["direct_messages_undated"], hc["as_logged"]["direct_messages_listed"]), (689, 0))
        kept = hc["who_talked_to_whom"]["recipients_kept"]["message_recall"]
        self.assertEqual((kept["k"], kept["n"]), (689, 689), "every logged recipient becomes a direct message once dated")
        for g in res["groups"].values():      # the shares are the counts they say they are
            for m in g["attribution"]["methods"].values():
                for r in m.values():
                    self.assertEqual(r["share"], round(r["k"] / r["n"], 4))
                    self.assertTrue(r["ci95"][0] <= r["share"] <= r["ci95"][1])

    def test_saved_results_are_what_the_tool_gives_now(self):
        res = saved_or_skip(self, "who_and_when")
        same_tool_or_skip(self, res)
        now = isolated("recheck", "who_and_when")
        self.assertEqual(now["groups"], res["groups"])
        self.assertEqual(now["false_alarms_all"], res["false_alarms_all"])
        self.assertEqual(now["attribution_all"], {k: v for k, v in res["attribution_all"].items() if k != "published_for_scale"})
        a = res["attribution_all"]["methods"]
        self.assertEqual((a["tool_first_sign"]["agent"]["k"], a["tool_first_sign"]["step"]["k"]), (54, 25))
        self.assertEqual((a["baseline_busiest_agent"]["agent"]["k"], a["baseline_last_step"]["agent"]["k"]), (72, 80))
        w = res["groups"]["Hand-Crafted"]["who_talked_to_whom"]["recipients_withheld"]
        self.assertEqual((w["pair_recall"]["k"], w["pair_recall"]["n"], w["message_recall"]["k"]), (91, 92, 62))
        self.assertEqual(res["false_alarms_all"]["by_rule_auto_pack"]["alert-coord2"]["k"], 181)


@unittest.skipUnless(HAS_MAST, "datasets-ext/mast_data is not downloaded")
class MastDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = isolated("counts", "mast_data")

    def test_what_the_reader_loads(self):
        c = self.counts
        self.assertEqual((c["runs_in_file"], c["runs"], c["records"], c["addressed"], c["timed"], c["actors"]),
                         (1642, 1640, 37805, 13441, 24461, 37))
        self.assertEqual(c["by_layout"], {"AG2": [597, 3035, 0], "AppWorld": [30, 2656, 460], "ChatDev": [330, 17206, 12500],
                                          "HyperAgent": [28, 2800, 481], "Magentic": [195, 4853, 0], "MetaGPT": [430, 2574, 0],
                                          "OpenManus": [30, 4681, 0]})
        self.assertEqual((c["left_out"], c["failed"]), (81315, 1236))

    def test_the_small_file_loads_through_the_tool(self):
        h = self.counts["human_file"]
        self.assertEqual(h["format"], readers.FORMATS["mast"])
        self.assertEqual((h["records"], h["runs"], h["addressed"]), (297, 9, 87))

    def test_saved_results_agree_with_the_reader(self):
        res = saved_or_skip(self, "mast_data")
        self.assertEqual(res["totals"], {"runs": 1640, "records": 37805, "records_with_time": 24461, "logged_messages_with_recipient": 13441})
        self.assertEqual(res["parsing"]["runs_with_no_record"], ["HyperAgent_SWE_Bench_Lite_Claude_28", "HyperAgent_SWE_Bench_Lite_Claude_29"])
        self.assertEqual(res["revision"], "95118ac951421753cf1deb87ddea3b01e693c41b")
        lv = res["labels_vs_alarms"]
        self.assertEqual((lv["runs_with_a_failure_mode"], lv["runs_with_none"], lv["runs_without_full_labels"]), (1236, 400, 4))
        for g, v in res["groups"].items():
            w = v["who_talked_to_whom"]
            self.assertEqual(w is not None, g in RF.MAST_ADDRESSED, g)
            if w:
                kept = w["recipients_kept"]["message_recall"]
                self.assertEqual((kept["k"], kept["n"]), (v["logged_messages_with_recipient"],) * 2, g)
            self.assertEqual(v["clock"], "logged times" if g in RF.MAST_TIMED else "step clock")
            self.assertEqual("as_logged" in v, g not in RF.MAST_TIMED)

    def test_saved_results_are_what_the_tool_gives_now(self):
        res = saved_or_skip(self, "mast_data")
        same_tool_or_skip(self, res)
        now = isolated("recheck", "mast_data")
        for g in ("AppWorld", "HyperAgent"):
            self.assertEqual(now["groups"][g], {k: v for k, v in res["groups"][g].items() if k != "runs_in_file"}, g)
        w = res["who_talked_to_whom_all"]["recipients_withheld"]
        self.assertEqual((w["pair_recall"]["k"], w["pair_recall"]["n"]), (2242, 2800))
        self.assertEqual(res["false_alarms_all"]["by_rule_auto_pack"]["alert-coord2"]["k"], 1567)
        self.assertEqual(res["false_alarms_all"]["by_rule_auto_pack"]["baseline-volume"]["k"], 0)


# ---------------------------------------------------------------------------------------------- the two stories and the summaries

class StoryTest(unittest.TestCase):
    SLUGS = {"who-failed-and-when": "who_and_when", "seven-frameworks-no-attack": "mast_data"}

    def stories(self):
        out = {}
        for slug in self.SLUGS:
            p = os.path.join(STORIES, slug + ".json")
            if not os.path.isfile(p):
                self.skipTest("docs/ is not in this copy")
            with open(p, encoding="utf-8") as f:
                out[slug] = json.load(f)
        return out

    def test_stories_hold_no_numbers_and_link_every_claim(self):
        for slug, s in self.stories().items():
            self.assertEqual(s["slug"], slug)
            text = " ".join(b.get("p") or b.get("note") or b.get("h") or "" for b in s["body"])
            self.assertEqual(set(re.findall(r"\[\[([a-z0-9]+)\|", text)), set(s["claims"]), slug)
            plain = re.sub(r"\{[A-Za-z0-9_]+\}", "", re.sub(r"\[\[[a-z0-9]+\|(.+?)\]\]", r"\1", text))
            self.assertNotRegex(plain, r"\d", f"{slug}: numbers come from the results file, not the story")
            used = set(re.findall(r"\{([A-Za-z0-9_]+)\}", text + s["dek"]))
            for c in s["claims"].values():
                used |= set(c.get("figures", []))
            self.assertLessEqual(used, set(s["figures"]), slug)

    def test_stories_carry_the_credit_line_and_the_licence(self):
        s = self.stories()
        self.assertIn("MIT License, Copyright (c) 2025 Ming Yin", s["who-failed-and-when"]["source"]["attribution"])
        self.assertIn("arXiv:2505.00212", s["who-failed-and-when"]["source"]["attribution"])
        self.assertIn("CC BY 4.0", s["seven-frameworks-no-attack"]["source"]["attribution"])
        self.assertIn("Changes:", s["seven-frameworks-no-attack"]["source"]["attribution"], "CC BY asks to say what was changed")
        for slug, story in s.items():
            cited = [r for c in story["claims"].values() for r in c.get("records", [])]
            self.assertTrue(cited, slug)
            for c in story["claims"].values():      # a claim that shows record text says whose it is
                if c.get("records") and c is not next(iter(story["claims"].values())):
                    self.assertTrue(c.get("caveat") or story["source"]["attribution"])

    def test_every_figure_resolves_in_the_saved_results(self):
        from agenttrace.tools import build_investigations as B
        for slug, s in self.stories().items():
            res = FE.saved(self.SLUGS[slug])
            if res is None:
                self.skipTest("the results are not here")
            for key, spec in s["figures"].items():
                self.assertEqual(spec["from"], f"reports/external/{self.SLUGS[slug]}/results.json", key)
                v = B.dig(res, spec["path"])
                self.assertIsInstance(v, (int, float), f"{slug}: {key}")
                self.assertNotEqual(B.fmt_value(v, spec["as"]), "–", key)

    def test_summary_is_written_from_the_results(self):
        for name in self.SLUGS.values():
            res = FE.saved(name)
            if res is None:
                self.skipTest("the results are not here")
            with open(os.path.join(FE.OUT, name, "summary.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), FE.summary_md(res), name)
            self.assertIn(f"{res['totals']['runs']:,} runs, {res['totals']['records']:,} records", FE.summary_md(res))
            self.assertIn("Credit: " + FE.SOURCES[name]["attribution"], FE.summary_md(res))

    def test_registry_entries_match_the_results(self):
        with open(os.path.join(ROOT, "agenttrace", "claims", "datasets.json"), encoding="utf-8") as f:
            entries = {e["id"]: e for e in json.load(f)["entries"]}
        for name in self.SLUGS.values():
            res = FE.saved(name)
            if res is None:
                self.skipTest("the results are not here")
            loc = entries[name]["local"]
            self.assertEqual(entries[name]["status"], "analysed")
            self.assertEqual((loc["records"], loc["runs"], loc["messages"], loc["timed_records"]),
                             (res["totals"]["records"], res["totals"]["runs"], res["totals"]["logged_messages_with_recipient"],
                              res["totals"]["records_with_time"]), name)
            self.assertIn(res["revision"], loc["revision"])


if __name__ == "__main__":
    unittest.main()
