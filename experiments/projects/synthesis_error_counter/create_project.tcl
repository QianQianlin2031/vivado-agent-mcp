set script_dir [file dirname [file normalize [info script]]]
set project_dir [file join $script_dir vivado]

create_project -force synthesis_error_counter $project_dir -part xc7a35tcpg236-1
add_files -norecurse [file join $script_dir src counter_top.v]
add_files -fileset constrs_1 -norecurse [file join $script_dir constraints basys3.xdc]
set_property top counter_top [current_fileset]
update_compile_order -fileset sources_1

puts "SYNTHESIS_ERROR_PROJECT=[file join $project_dir synthesis_error_counter.xpr]"

