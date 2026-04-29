// eml_acos.v -- acos(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implemented via the identity
//   acos(x) = pi/2 - asin(x)
// using a 3-term asin Taylor series valid for x in [-0.5, 0.5].
//
// Pipeline: 4 stages.

`default_nettype none

module eml_acos #(
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

    localparam signed [WIDTH-1:0] ONE        = 1 <<< FRAC;
    localparam signed [WIDTH-1:0] ONE_SIXTH  = ONE / 6;
    localparam signed [WIDTH-1:0] THREE_40TH = (3 * ONE) / 40;
    localparam signed [WIDTH-1:0] FIFT_336TH = (15 * ONE) / 336;
    // pi/2 in Q<WIDTH-FRAC>.<FRAC>; computed once at elaboration.
    localparam signed [WIDTH-1:0] HALF_PI = (ONE * 314159) / 200000;

    function signed [WIDTH-1:0] qmul;
        input signed [WIDTH-1:0] a;
        input signed [WIDTH-1:0] b;
        reg signed [2*WIDTH-1:0] product;
        begin
            product = a * b;
            qmul = product >>> FRAC;
        end
    endfunction

    reg signed [WIDTH-1:0] x1, x2, x3, x5, x7;
    reg signed [WIDTH-1:0] acc;
    reg [PIPELINE_STAGES-1:0] valid_pipe;

    always @(posedge clk) begin
        if (rst) begin
            x1 <= '0; x2 <= '0; x3 <= '0; x5 <= '0; x7 <= '0;
            acc <= '0;
            valid_pipe <= '0;
        end else begin
            x1 <= x_in;
            x2 <= qmul(x_in, x_in);
            x3 <= qmul(x2, x1);
            x5 <= qmul(qmul(x2, x2), x1);
            x7 <= qmul(qmul(qmul(x2, x2), x2), x1);
            // acos(x) = pi/2 - asin(x)
            acc <= HALF_PI
                 - x1
                 - qmul(x3, ONE_SIXTH)
                 - qmul(x5, THREE_40TH)
                 - qmul(x7, FIFT_336TH);
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = acc;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
