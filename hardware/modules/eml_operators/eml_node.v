// eml_node.v -- the EML primitive in synthesizable Verilog.
//
// Computes y = exp(x_in) - ln(y_in) where y_in > 0.
//
// Status: SCAFFOLD. Real implementation depends on the chosen
// transcendental backend (CORDIC vs polynomial vs LUT) selected
// by the FPGA allocator (see hardware/allocator/precision_selector.py).
//
// Parameters:
//   WIDTH         total bit width of the data path (e.g. 32)
//   FRAC          fractional bits for fixed-point (0 = floating)
//   TRANSCENDENTAL  one of "cordic", "poly", "lut"
//   PIPELINE_STAGES number of pipeline stages (latency in cycles)
//
// I/O:
//   clk, rst    standard synchronous clock + active-high reset
//   in_valid    asserted when x_in / y_in carry valid data
//   out_valid   asserted when result is valid (PIPELINE_STAGES later)

`default_nettype none

module eml_node #(
    parameter WIDTH           = 32,
    parameter FRAC            = 16,
    parameter TRANSCENDENTAL  = "cordic",
    parameter PIPELINE_STAGES = 8
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  in_valid,
    input  wire signed [WIDTH-1:0] x_in,
    input  wire signed [WIDTH-1:0] y_in,
    output wire                  out_valid,
    output wire signed [WIDTH-1:0] result
);

    // ── Stage 1: exp(x_in) ────────────────────────────────────
    // Output of the chosen exp engine after PIPELINE_STAGES/2 cycles.
    wire signed [WIDTH-1:0] exp_x;
    wire                    exp_valid;

    // TODO: instantiate one of:
    //   cordic_exp #(.WIDTH(WIDTH), .FRAC(FRAC)) ...
    //   poly_exp   #(.WIDTH(WIDTH), .FRAC(FRAC)) ...
    //   lut_exp    #(.WIDTH(WIDTH), .FRAC(FRAC)) ...
    // chosen by the allocator at compile time and passed via
    // TRANSCENDENTAL parameter.

    // ── Stage 2: ln(y_in) ─────────────────────────────────────
    wire signed [WIDTH-1:0] ln_y;
    wire                    ln_valid;

    // TODO: cordic_ln / poly_ln / lut_ln per allocator.

    // ── Stage 3: subtract ─────────────────────────────────────
    // exp(x) - ln(y), both already at the same fixed-point scale.
    reg signed [WIDTH-1:0] result_r;
    reg                    valid_r;

    always @(posedge clk) begin
        if (rst) begin
            result_r <= '0;
            valid_r  <= 1'b0;
        end else begin
            valid_r  <= exp_valid && ln_valid;
            if (exp_valid && ln_valid) begin
                result_r <= exp_x - ln_y;
            end
        end
    end

    assign result    = result_r;
    assign out_valid = valid_r;

endmodule

`default_nettype wire
