`timescale 1ns / 1ps

module counter_top (
    input  wire clk,
    input  wire rst,
    output wire led
);

    reg [25:0] counter = 26'd0;

    always @(posedge clk) begin
        if (rst)
            counter <= 26'd0;
        else
            counter <= counter + 1'b1;
    end

    assign led = counter[25];

endmodule

