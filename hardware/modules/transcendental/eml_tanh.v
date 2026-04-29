// eml_tanh.v -- tanh(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implements 4-term Taylor series valid for
// x in [-1, 1]. Outside this range tanh saturates at +/-1, which
// the caller can clamp via mg_clamp.
//
//   tanh(x) ~= x - x^3/3 + 2*x^5/15 - 17*x^7/315    (|x| <= 1)
//
// Pipeline: 4 stages.

`default_nettype none

module eml_tanh #(
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

    localparam signed [WIDTH-1:0] ONE          = 1 <<< FRAC;
    localparam signed [WIDTH-1:0] ONE_THIRD    = ONE / 3;
    localparam signed [WIDTH-1:0] TWO_15THS    = (2 * ONE) / 15;
    localparam signed [WIDTH-1:0] SEVNTN_315TH = (17 * ONE) / 315;

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
            acc <= x1
                 - qmul(x3, ONE_THIRD)
                 + qmul(x5, TWO_15THS)
                 - qmul(x7, SEVNTN_315TH);
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = acc;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
