#!/usr/bin/env python3
"""Actual ARM hardware-first UX: capture, key edges, chrome and input recovery."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from qemu_control import Qmp, stop_process
from qtest_pxa import QTest, equal
from shell_control import (DISPLAY,INPUT,MAILBOX,MACHINE,UX_FIELDS,physical,record,ux_record,
                           pointer_phase_wire as pointer,hardware_key_wire as key,wire,pointer_wire)
from smoke_display import sha
from smoke_e2a import qemu_version
from smoke_security import words
from smoke_shell import ARTIFACTS,IMAGE,USER_IMAGE,capture,verify_reference,await_ticks,read_trace,check_tables
from smoke_shell_pointer import prepare,observe,trace_item
from smoke_tasks import task_records

ROOT=Path(__file__).resolve().parents[1]
OUT=ARTIFACTS/"adaptive"


def bindings():
    previous=json.loads((ARTIFACTS/"execution/result.json").read_text())
    paths={ROOT/name for name in previous["source_sha256"]}
    paths.update(path for folder in ("shell","ui/src") for path in (ROOT/folder).rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts and path.name!=".DS_Store"
                 and not any(part in ("target","local") for part in path.relative_to(ROOT).parts))
    paths.update(ROOT/name for name in ("tools/smoke_shell_adaptive.py","tools/run_shell.py","tools/crosshair_gui.swift",
        "tools/shell_control.py","tools/smoke_shell_pointer.py","tools/test_shell_input.py",
        "scripts/test-shell-adaptive.sh","scripts/test-wave007-2.sh"))
    return {str(path.relative_to(ROOT)):sha(path.read_bytes()) for path in sorted(paths)}


def run(qemu,image,user,exporter):
    result={"result":"FAIL","boots":[],"machine":MACHINE,"accelerator":"tcg",
            "scope":"actual ARM Shell; emulator semantic input, no physical PDA driver/timing claim"}
    source=bindings();result["source_sha256"]=source
    with tempfile.TemporaryDirectory(prefix="crosshair-adaptive-") as temporary:
        qmp_path,memory_path=Path(temporary)/"qmp",Path(temporary)/"memory"
        command=[qemu,"-machine",MACHINE,"-cpu","pxa260","-accel","tcg","-S","-display","none",
                 "-monitor","none","-serial","stdio","-nic","none","-device",f"loader,file={IMAGE/'crosshair-shell.elf'},cpu-num=0",
                 "-qmp",f"unix:{qmp_path},server=on,wait=off","-qtest",f"unix:{memory_path},server=on,wait=off",
                 "-qtest-log",str(OUT/"memory-server.log")]
        result["command"]=command
        with (OUT/"qemu-uart.log").open("wb") as uart,(OUT/"qemu-stderr.log").open("wb") as stderr,(OUT/"memory-protocol.log").open("w") as transcript:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=uart,stderr=stderr)
            qmp=memory=None
            try:
                qmp,memory=Qmp(qmp_path,process),QTest(memory_path,process,transcript)
                for boot,name in enumerate(("phases","adaptive-reset")):
                    directory=OUT/name;directory.mkdir(parents=True,exist_ok=True)
                    prepare(qmp,memory,image)
                    delivered=handled=0
                    initial=observe(qmp,memory,process,image,user,0,0)
                    initial.update(name="initial",ux=ux_record(memory,user["symbols"]))
                    states=[initial];trace=[dict(trace_item(initial),ux=initial["ux"])]
                    captures={0:capture(qmp,initial["record"],directory/"step-00")}
                    equal((initial["ux"]["chrome_mode"],initial["ux"]["content_y"],initial["ux"]["content_height"]),(0,24,296),"one Standard top bar; content reaches screen bottom")
                    def step(label,value,checks=None,ui=True,delta=None,shot=False):
                        nonlocal delivered,handled
                        before=states[-1]["ux"]
                        memory.writel(INPUT+8,value);qmp.request("cont");delivered+=1;handled+=int(ui)
                        state=observe(qmp,memory,process,image,user,delivered,handled,value)
                        state.update(name=label,ux=ux_record(memory,user["symbols"]))
                        for field,expected in (checks or {}).items():
                            actual=state["ux"].get(field,state["user"]["snapshot"].get(field))
                            equal(actual,expected,f"{label}: {field}")
                        if delta is not None:
                            equal(state["ux"]["actions_invoked"]-before["actions_invoked"],delta,f"{label}: exact activations")
                        states.append(state);trace.append(dict(trace_item(state),ux=state["ux"]))
                        if shot:
                            index=len(trace)-1;captures[index]=capture(qmp,state["record"],directory/f"step-{index:02d}")
                        return state
                    if name=="phases":
                        step("press-no-activation",pointer(1,40,68),{"screen":0,"pointer_active":1},delta=0,shot=True)
                        step("move-within-target",pointer(2,41,68),{"screen":0,"pointer_cancelled":0},delta=0)
                        step("moved-hold-rejected",pointer(5,held_ms=1000),{"screen":0,"panel":0,"pointer_active":1},delta=0)
                        step("release-one-tap",pointer(3,40,68),{"screen":1,"pointer_active":0},delta=1,shot=True)
                        step("home",wire(7),{"screen":0})
                        step("press-before-drag",pointer(1,40,68),{"pointer_active":1},delta=0)
                        step("drag-out",pointer(2,130,150),{"pointer_cancelled":1},delta=0,shot=True)
                        step("drag-back-still-cancelled",pointer(2,40,68),{"pointer_cancelled":1},delta=0)
                        step("drag-release-no-tap",pointer(3,40,68),{"screen":0,"pointer_active":0},delta=0,shot=True)
                        step("orphan-release",pointer(3,40,68),{"screen":0},delta=0)
                        step("orphan-hold",pointer(5,held_ms=1000),{"panel":0},delta=0)
                        step("press-before-short-hold",pointer(1,40,68),{"pointer_active":1})
                        step("hold599-no-context",pointer(5,held_ms=599),{"panel":0,"pointer_active":1},delta=0)
                        step("hold600-context",pointer(5,held_ms=600),{"panel":4,"pointer_active":0},delta=0,shot=True)
                        step("post-hold-release-suppressed",pointer(3,40,68),{"panel":4},delta=0)
                        step("back-closes-panel",wire(5),{"screen":0,"panel":0})
                        step("press-before-cancel",pointer(1,40,68),{"pointer_active":1})
                        step("explicit-pointer-cancel",pointer(4),{"pointer_active":0},delta=0)
                        step("held-up",key(0,0),{"held_keys":1})
                        step("press-with-key-held",pointer(1,40,68),{"pointer_active":1,"held_keys":1})
                        step("source-failure",0x0800E007,{"pointer_active":0,"held_keys":0,"screen":0},ui=False,delta=0,shot=True)
                        step("stale-release-after-failure",pointer(3,40,68),{"screen":0},delta=0)
                        step("home-press",key(0,7),{"screen":0,"held_keys":128})
                        step("home-release",key(2,7),{"held_keys":0},delta=0)
                        step("fresh-press",pointer(1,40,68),{"screen":0,"pointer_active":1},delta=0)
                        step("fresh-release-recovers",pointer(3,40,68),{"screen":1},delta=1,shot=True)
                        step("home-after-recovery",wire(7),{"screen":0})
                        step("press-before-invalid-move",pointer(1,40,68),{"pointer_active":1})
                        step("invalid-move-cancels-input",pointer(2,240,68),{"pointer_active":0,"held_keys":0},ui=False,delta=0)
                        step("reserved-start-recovers",wire(11),{"screen":2},shot=True)
                        step("launcher-press-for-context",pointer(1,30,70),{"screen":2,"pointer_active":1},delta=0)
                        step("launcher-measured-context",pointer(5,held_ms=600),{"screen":2,"panel":2,"pointer_active":0},delta=0,shot=True)
                        step("context-release-suppressed",pointer(3,30,70),{"screen":2,"panel":2},delta=0)
                        step("back-closes-context",wire(5),{"screen":2,"panel":0})
                        step("panel-before-outside-tap",wire(12),{"panel":4})
                        step("outside-panel-press",pointer(1,10,140),{"panel":4,"pointer_active":1},delta=0)
                        step("outside-panel-release-dismisses",pointer(3,10,140),{"screen":2,"panel":0,"pointer_active":0},delta=0,shot=True)
                        step("open-settings-for-modal",pointer_wire(30,140),{"screen":5})
                        step("open-modal-reset",pointer_wire(30,138),{"screen":5,"panel":3},shot=True)
                        step("outside-dialog-press",pointer(1,10,80),{"panel":3,"pointer_active":1},delta=0)
                        step("outside-dialog-release-inert",pointer(3,10,80),{"screen":5,"panel":3,"pointer_active":0,"theme":0},delta=0,shot=True)
                        step("back-closes-dialog",wire(5),{"screen":5,"panel":0})
                        step("home-after-modal",wire(7),{"screen":0})
                    else:
                        step("hardware-start-command",wire(11),{"screen":2})
                        step("open-about-standard",wire(4),{"screen":3,"chrome_mode":0},shot=True)
                        step("temporary-panel",wire(12),{"panel":4},shot=True)
                        step("enter-compact",pointer_wire(30,214),{"chrome_mode":1,"content_y":16,"content_height":304,"panel":0},shot=True)
                        step("compact-scroll",wire(1),{"scroll_offset":1},shot=True)
                        step("panel-in-compact",wire(12),{"panel":4})
                        step("enter-immersive",pointer_wire(30,240),{"chrome_mode":2,"content_y":0,"content_height":320,"scroll_offset":1},shot=True)
                        step("immersive-edge-press",pointer(1,100,1),{"pointer_active":1},delta=0)
                        step("immersive-edge-recovery",pointer(2,100,15),{"panel":4,"pointer_active":0},delta=0,shot=True)
                        step("edge-release-suppressed",pointer(3,100,15),{"panel":4},delta=0)
                        step("return-standard",pointer_wire(30,188),{"chrome_mode":0,"content_y":24,"content_height":296,"scroll_offset":1},shot=True)
                        step("back-preserves-history",wire(5),{"screen":2,"history_depth":1})
                        step("home-desktop",wire(7),{"screen":0})
                        step("down-press",key(0,1),{"desktop_selected":1,"held_keys":2})
                        step("down-repeat",key(1,1),{"desktop_selected":2,"held_keys":2})
                        step("down-repeat-clamped",key(1,1),{"desktop_selected":2},delta=0)
                        step("down-release",key(2,1),{"held_keys":0},delta=0)
                        step("select-press-opens",key(0,4),{"screen":4})
                        step("select-repeat-no-reinvoke",key(1,4),{"screen":4},delta=0)
                        step("select-release",key(2,4),{"held_keys":0},delta=0)
                        step("home-before-loss",wire(7),{"screen":0})
                        step("up-held-before-loss",key(0,0),{"held_keys":1})
                        step("capture-before-overflow",pointer(1,40,68),{"pointer_active":1,"held_keys":1},delta=0,shot=True)
                        # Real hardware FIFO8 -> kernel FIFO4: use plain text so
                        # accepted tail cannot legitimately begin a fresh gesture.
                        previous_cancels=states[-1]["ux"]["input_cancels"]
                        for _ in range(8):memory.writel(INPUT+8,0x08000058)
                        qmp.request("cont");old_handled=handled;delivered+=4;handled+=4
                        final=observe(qmp,memory,process,image,user,delivered,handled,0x08000058)
                        final.update(name="actual-queue-overflow",ux=ux_record(memory,user["symbols"]))
                        equal((final["record"]["queue_dropped"],final["ux"]["pointer_active"],final["ux"]["held_keys"]),(4,0,0),"actual queue-loss counter cancels active pointer and held key")
                        equal(final["ux"]["input_cancels"]>previous_cancels,True,"actual overflow triggered bounded cancellation")
                        journal=read_trace(memory,user["symbols"],handled)
                        for index in range(old_handled+1,handled+1):
                            item=journal[index]
                            item["ux"]=dict(zip(UX_FIELDS,words(memory,physical(user["symbols"]["SHELL_UX_TRACE"])+index*80,20)))
                            item["render_metrics"]=words(memory,physical(user["symbols"]["SHELL_RENDER_TRACE"])+index*32,8)
                            trace.append(item)
                        states.append(final);index=len(trace)-1;captures[index]=capture(qmp,final["record"],directory/f"step-{index:02d}")
                        step("overflow-stale-release",pointer(3,40,68),{"screen":0,"pointer_active":0},delta=0)
                        step("escape-recovery-home-press",key(0,7),{"screen":0})
                        step("escape-recovery-home-release",key(2,7),{"held_keys":0})
                        step("fresh-press-after-loss",pointer(1,40,68),{"screen":0,"pointer_active":1},delta=0)
                        step("fresh-release-after-loss",pointer(3,40,68),{"screen":1,"pointer_active":0},delta=1,shot=True)
                    parity=verify_reference(exporter,directory,trace,states,captures)
                    frames=json.loads((directory/"host/frames.json").read_text())["frames"]
                    for item,frame in zip(trace,frames):
                        equal(frame["ux_words"],[item["ux"][field]for field in UX_FIELDS],"all20 actual ARM adaptive UX words equal shared host execution")
                        equal(frame["render_stats"],item["render_metrics"],"all8 actual ARM render-cost words equal host")
                    before=record(memory,image["symbols"]["CROSSHAIR_SHELL_RECORD"]);counter=memory.readl(0xA0201000)
                    qmp.request("cont");await_ticks(memory,image["symbols"],before["ticks"]+3,process);qmp.request("stop")
                    after=record(memory,image["symbols"]["CROSSHAIR_SHELL_RECORD"])
                    equal((after["events_delivered"],after["frames"]),(delivered,before["frames"]),"no input/render loop while waiting")
                    equal(memory.readl(0xA0201000)>counter,True,"noncooperative second User workload continues through all UX cases")
                    equal(task_records(memory,image["symbols"]["TASKS"])[1]["state"],4,"Shell remains blocked rather than polling")
                    equal(memory.readl(INPUT+0x10),0,"new normal phases/keys never overflow hardware FIFO")
                    result["boots"].append({"name":name,"events":delivered,"ui_events":handled,"states":states,"trace":trace,
                        "captures":captures,"parity":parity,"page_tables":check_tables(memory,image["symbols"],after),
                        "waiting_progress":{"before":before,"after":after,"busy_counter_before":counter,"busy_counter_after":memory.readl(0xA0201000)}})
                    if boot==0:qmp.request("system_reset")
                equal(bindings(),source,"source bytes frozen during adaptive execution")
                qmp.request("quit");process.wait(timeout=3);equal(process.returncode,0,"clean adaptive QEMU exit")
                result.update(result="PASS",boots_completed=2,events=sum(boot["events"]for boot in result["boots"]),
                    pixel_comparisons=sum(boot["parity"]["pixel_comparisons"]for boot in result["boots"]),
                    image_sha256=image["sha256"],user_image_sha256=user["sha256"],qemu_version=qemu_version(qemu),
                    qemu_sha256=sha(Path(shutil.which(qemu)or qemu).read_bytes()))
            except Exception as error:
                result["error"]=f"{type(error).__name__}: {error}"
                if qmp and memory and process.poll() is None:
                    try:qmp.request("stop");result["failure_record"]=record(memory,image["symbols"]["CROSSHAIR_SHELL_RECORD"]);result["failure_ux"]=ux_record(memory,user["symbols"])
                    except Exception:pass
                raise
            finally:
                if memory:memory.close()
                if qmp:qmp.close()
                stop_process(process);(OUT/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument("--qemu",default=os.environ.get("QEMU_DISPLAY_TEST",str(ROOT/"local/qemu-display-test/bin/qemu-system-arm")))
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"result.json").write_text('{"result":"FAIL","error":"test not completed"}\n')
    image=json.loads((IMAGE/"image.json").read_text());user=json.loads((USER_IMAGE/"user-image.json").read_text())
    for directory,manifest in ((IMAGE,image),(USER_IMAGE,user)):
        equal({name:sha((directory/name).read_bytes())for name in manifest["sha256"]},manifest["sha256"],"current adaptive image hashes")
    exporter=Path((ARTIFACTS/"host/exporter-path.txt").read_text().strip());r=run(args.qemu,image,user,exporter)
    print(f"PASS adaptive Shell: {r['boots_completed']} real ARM boots, {r['events']} input records, {r['pixel_comparisons']} host/ARM/QEMU pixels; phases/keys/chrome/loss recovery and Busy progress")


if __name__=="__main__":main()
