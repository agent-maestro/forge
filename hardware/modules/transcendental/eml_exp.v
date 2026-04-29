// eml_exp.v -- exp(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implements a 4-term Taylor series valid for
// x in [-1, 1]. The FPGA allocator (Patent #14) is expected to
// swap in CORDIC or LUT-based kernels for wider input ranges.
//
//   exp(x) ~= 1 + x + x^2/2 + x^3/6 + x^4/24      (|x| <= 1)
//
// Pipeline: 4 stages (one multiply + accumulate per stage).
//
// Parameters:
//   WIDTH            data path width in bits (default 32)
//   FRAC             fractional bits  (default 16, i.e. Q16.16)
//   PIPELINE_STAGES  fixed at 4 in this scaffold
//
// I/O:
//   clk, rst    standard synchronous clock + active-high reset
//   in_valid    high when x_in is valid this cycle
//   x_in        signed Q<WIDTH-FRAC>.<FRAC> argument
//   out_valid   high when result is valid (4 cycles later)
//   result      signed Q<WIDTH-FRAC>.<FRAC> approximation of exp(x)

`default_nettype none

module eml_exp #(
    parameter WIDTH           = 32,
    parameter FRAC            = 16,
    parameter PIPELINE_STAGES = 4
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  in_valid,
    input  wire signed [WIDTH-1:0] x_in,
    output wire                  out_valid,
    output wire signed [WIDTH-1:0] result
);

    // Q-format constants
    localparam signed [WIDTH-1:0] ONE       = 1 <<< FRAC;
    localparam signed [WIDTH-1:0] HALF      = ONE / 2;
    localparam signed [WIDTH-1:0] ONE_SIXTH = ONE / 6;
    localparam signed [WIDTH-1:0] ONE_24TH  = ONE / 24;

    // Helper: Q-format multiply with arithmetic shift.
    // (a * b) >>> FRAC, sign-extended through 2*WIDTH.
    function signed [WIDTH-1:0] qmul;
        input signed [WIDTH-1:0] a;
        input signed [WIDTH-1:0] b;
        reg signed [2*WIDTH-1:0] product;
        begin
            product = a * b;
            qmul = product >>> FRAC;
        end
    endfunction

    // Pipeline registers: x_n holds x^n at stage n.
    reg signed [WIDTH-1:0] x1, x2, x3, x4;
    reg signed [WIDTH-1:0] acc;
    reg [PIPELINE_STAGES-1:0] valid_pipe;

    always @(posedge clk) begin
        if (rst) begin
            x1 <= '0; x2 <= '0; x3 <= '0; x4 <= '0;
            acc <= '0;
            valid_pipe <= '0;
        end else begin
            // Stage 1: capture x, compute x^2.
            x1 <= x_in;
            x2 <= qmul(x_in, x_in);
            // Stage 2: x^3 = x^2 * x_prev.
            x3 <= qmul(x2, x1);
            // Stage 3: x^4 = x^2 * x^2.
            x4 <= qmul(x2, x2);
            // Stage 4: accumulate Taylor terms.
            acc <= ONE
                 + x1
                 + qmul(x2, HALF)
                 + qmul(x3, ONE_SIXTH)
                 + qmul(x4, ONE_24TH);
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = acc;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
