set script_dir [file dirname [file normalize [info script]]]
set project_dir [file join $script_dir vivado]

create_project -force manual_build_demo $project_dir -part xc7a35tcpg236-1
add_files -norecurse [file join $script_dir src counter_top.v]
add_files -fileset constrs_1 -norecurse [file join $script_dir constraints basys3.xdc]
set_property top counter_top [current_fileset]
update_compile_order -fileset sources_1

puts "MANUAL_BUILD_DEMO_PROJECT=[file join $project_dir manual_build_demo.xpr]"

