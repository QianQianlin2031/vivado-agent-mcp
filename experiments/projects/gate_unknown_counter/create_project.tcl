set script_dir [file dirname [file normalize [info script]]]
set project_dir [file join $script_dir vivado]

create_project -force gate_unknown_counter $project_dir -part xc7a35tcpg236-1
add_files -norecurse [file join $script_dir src counter_top.v]
add_files -fileset constrs_1 -norecurse [file join $script_dir constraints basys3_without_clock.xdc]
set_property top counter_top [current_fileset]
update_compile_order -fileset sources_1

puts "GATE_UNKNOWN_PROJECT=[file join $project_dir gate_unknown_counter.xpr]"

