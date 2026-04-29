// eml_atan.v -- atan(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implements 4-term Taylor series valid for
// x in [-1, 1]. Outside this range use the identity
//   atan(x) = pi/2 - atan(1/x)
// to fold |x| > 1 back into the safe band.
//
//   atan(x) ~= x - x^3/3 + x^5/5 - x^7/7    (|x| <= 1)
//
// Pipeline: 4 stages.

`default_nettype none

module eml_atan #(
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

    localparam signed [WIDTH-1:0] ONE         = 1 <<< FRAC;
    localparam signed [WIDTH-1:0] ONE_THIRD   = ONE / 3;
    localparam signed [WIDTH-1:0] ONE_FIFTH   = ONE / 5;
    localparam signed [WIDTH-1:0] ONE_SEVENTH = ONE / 7;

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
                 + qmul(x5, ONE_FIFTH)
                 - qmul(x7, ONE_SEVENTH);
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = acc;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
