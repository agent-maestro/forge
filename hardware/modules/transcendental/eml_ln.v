// eml_ln.v -- ln(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implements ln(1+u) Taylor series valid for
// u in [-0.5, 0.5], i.e. x in [0.5, 1.5]. Caller responsible
// for range reduction (e.g. ln(2^k * m) = k*ln2 + ln(m)).
//
//   ln(1+u) ~= u - u^2/2 + u^3/3 - u^4/4    (|u| <= 0.5)
//
// Pipeline: 4 stages.

`default_nettype none

module eml_ln #(
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
    localparam signed [WIDTH-1:0] HALF       = ONE / 2;
    localparam signed [WIDTH-1:0] ONE_THIRD  = ONE / 3;
    localparam signed [WIDTH-1:0] ONE_FOURTH = ONE / 4;

    function signed [WIDTH-1:0] qmul;
        input signed [WIDTH-1:0] a;
        input signed [WIDTH-1:0] b;
        reg signed [2*WIDTH-1:0] product;
        begin
            product = a * b;
            qmul = product >>> FRAC;
        end
    endfunction

    reg signed [WIDTH-1:0] u1, u2, u3, u4;
    reg signed [WIDTH-1:0] acc;
    reg [PIPELINE_STAGES-1:0] valid_pipe;

    always @(posedge clk) begin
        if (rst) begin
            u1 <= '0; u2 <= '0; u3 <= '0; u4 <= '0;
            acc <= '0;
            valid_pipe <= '0;
        end else begin
            // u = x - 1
            u1 <= x_in - ONE;
            u2 <= qmul(x_in - ONE, x_in - ONE);
            u3 <= qmul(u2, u1);
            u4 <= qmul(u2, u2);
            acc <= u1
                 - qmul(u2, HALF)
                 + qmul(u3, ONE_THIRD)
                 - qmul(u4, ONE_FOURTH);
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = acc;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
