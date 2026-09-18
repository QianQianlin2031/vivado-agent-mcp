"""Small, tagged Tcl queries used by the higher-level Agent workflows."""

from .vivado.protocol import validate_tcl_name

PROJECT_INFO = r"""
if {[catch {current_project} __project] || $__project eq ""} {
    puts "VAMCP_PROJECT:open=0"
} else {
    set __files [get_files -quiet]
    set __source_count 0
    set __constraint_count 0
    foreach __file $__files {
        if {[string equal -nocase [file extension $__file] ".xdc"]} {
            incr __constraint_count
        } else {
            incr __source_count
        }
    }
    set __synth_status ""
    set __impl_status ""
    if {[llength [get_runs -quiet synth_1]]} {
        set __synth_status [get_property STATUS [get_runs synth_1]]
    }
    if {[llength [get_runs -quiet impl_1]]} {
        set __impl_status [get_property STATUS [get_runs impl_1]]
    }
    puts "VAMCP_PROJECT:open=1"
    puts "VAMCP_PROJECT:name=[get_property NAME $__project]"
    puts "VAMCP_PROJECT:directory=[get_property DIRECTORY $__project]"
    puts "VAMCP_PROJECT:part=[get_property PART $__project]"
    puts "VAMCP_PROJECT:top=[get_property TOP [current_fileset]]"
    puts "VAMCP_PROJECT:source_count=$__source_count"
    puts "VAMCP_PROJECT:constraint_count=$__constraint_count"
    puts "VAMCP_PROJECT:synthesis_status=$__synth_status"
    puts "VAMCP_PROJECT:implementation_status=$__impl_status"
}
""".strip()


def launch_run(run_name: str, jobs: int) -> str:
    run_name = validate_tcl_name(run_name, label="run name")
    if not 1 <= jobs <= 64:
        raise ValueError("jobs must be between 1 and 64")
    return rf"""
set __runs [get_runs -quiet {run_name}]
if {{![llength $__runs]}} {{error "Vivado run does not exist: {run_name}"}}
set __run [lindex $__runs 0]
set __status [get_property STATUS $__run]
puts "VAMCP_LAUNCH:previous_status=$__status"
if {{[regexp -nocase {{running|queued}} $__status]}} {{
    puts "VAMCP_LAUNCH:started=0"
}} else {{
    if {{![regexp -nocase {{not started}} $__status]}} {{reset_run $__run}}
    launch_runs $__run -jobs {jobs}
    puts "VAMCP_LAUNCH:started=1"
}}
puts "VAMCP_LAUNCH:run_name={run_name}"
""".strip()


def launch_bitstream(jobs: int) -> str:
    if not 1 <= jobs <= 64:
        raise ValueError("jobs must be between 1 and 64")
    return rf"""
set __runs [get_runs -quiet impl_1]
if {{![llength $__runs]}} {{error "Vivado run does not exist: impl_1"}}
set __run [lindex $__runs 0]
set __status [get_property STATUS $__run]
puts "VAMCP_LAUNCH:previous_status=$__status"
if {{[regexp -nocase {{write_bitstream complete}} $__status]}} {{
    puts "VAMCP_LAUNCH:completed=1"
    puts "VAMCP_LAUNCH:started=0"
}} elseif {{[regexp -nocase {{running|queued}} $__status]}} {{
    puts "VAMCP_LAUNCH:completed=0"
    puts "VAMCP_LAUNCH:started=0"
}} else {{
    launch_runs $__run -to_step write_bitstream -jobs {jobs}
    puts "VAMCP_LAUNCH:completed=0"
    puts "VAMCP_LAUNCH:started=1"
}}
puts "VAMCP_LAUNCH:run_name=impl_1"
""".strip()


def inspect_run(run_name: str) -> str:
    run_name = validate_tcl_name(run_name, label="run name")
    return rf"""
set __runs [get_runs -quiet {run_name}]
if {{![llength $__runs]}} {{error "Vivado run does not exist: {run_name}"}}
set __run [lindex $__runs 0]
puts "VAMCP_RUN:status=[get_property STATUS $__run]"
puts "VAMCP_RUN:progress=[get_property PROGRESS $__run]"
puts "VAMCP_RUN:directory=[get_property DIRECTORY $__run]"
""".strip()


def diagnose_run(run_name: str, max_issues: int = 20) -> str:
    run_name = validate_tcl_name(run_name, label="run name")
    if not 1 <= max_issues <= 100:
        raise ValueError("max_issues must be between 1 and 100")
    return rf"""
set __runs [get_runs -quiet {run_name}]
if {{![llength $__runs]}} {{error "Vivado run does not exist: {run_name}"}}
set __run [lindex $__runs 0]
set __log [file join [get_property DIRECTORY $__run] runme.log]
set __errors 0
set __critical 0
set __emitted 0
if {{[file exists $__log]}} {{
    set __handle [open $__log r]
    set __content [read $__handle]
    close $__handle
    foreach __line [split $__content "\n"] {{
        if {{[regexp -nocase {{(^|[^A-Za-z])ERROR:}} $__line]}} {{
            incr __errors
            if {{$__emitted < {max_issues}}} {{puts "VAMCP_DIAG:issue=$__line"; incr __emitted}}
        }} elseif {{[regexp -nocase {{CRITICAL WARNING:}} $__line]}} {{
            incr __critical
            if {{$__emitted < {max_issues}}} {{puts "VAMCP_DIAG:issue=$__line"; incr __emitted}}
        }}
    }}
}}
puts "VAMCP_DIAG:log=$__log"
puts "VAMCP_DIAG:errors=$__errors"
puts "VAMCP_DIAG:critical_warnings=$__critical"
puts "VAMCP_DIAG:emitted=$__emitted"
""".strip()


READINESS_TIMING = r"""
set __runs [get_runs -quiet impl_1]
if {![llength $__runs]} {error "Vivado run does not exist: impl_1"}
set __run [lindex $__runs 0]
set __status [get_property STATUS $__run]
puts "VAMCP_READY:implementation_status=$__status"
if {[regexp -nocase {route_design complete|write_bitstream complete} $__status]} {
    open_run $__run
    set __setup [get_timing_paths -quiet -delay_type max -max_paths 1]
    set __hold [get_timing_paths -quiet -delay_type min -max_paths 1]
    if {[llength $__setup]} {
        puts "VAMCP_READY:setup_slack=[get_property SLACK [lindex $__setup 0]]"
    } else {
        puts "VAMCP_READY:setup_slack=NA"
    }
    if {[llength $__hold]} {
        puts "VAMCP_READY:hold_slack=[get_property SLACK [lindex $__hold 0]]"
    } else {
        puts "VAMCP_READY:hold_slack=NA"
    }
}
""".strip()
