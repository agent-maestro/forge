// eml_cos.v -- cos(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implements 3-term Taylor series valid for
// x in [-pi/2, pi/2]. Caller responsible for range reduction.
//
//   cos(x) ~= 1 - x^2/2 + x^4/24 - x^6/720    (|x| <= pi/2)
//
// Pipeline: 4 stages.

`default_nettype none

module eml_cos #(
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

    localparam signed [WIDTH-1:0] ONE       = 1 <<< FRAC;
    localparam signed [WIDTH-1:0] HALF      = ONE / 2;
    localparam signed [WIDTH-1:0] ONE_24TH  = ONE / 24;
    localparam signed [WIDTH-1:0] ONE_720TH = ONE / 720;

    function signed [WIDTH-1:0] qmul;
        input signed [WIDTH-1:0] a;
        input signed [WIDTH-1:0] b;
        reg signed [2*WIDTH-1:0] product;
        begin
            product = a * b;
            qmul = product >>> FRAC;
        end
    endfunction

    reg signed [WIDTH-1:0] x2, x4, x6;
    reg signed [WIDTH-1:0] acc;
    reg [PIPELINE_STAGES-1:0] valid_pipe;

    always @(posedge clk) begin
        if (rst) begin
            x2 <= '0; x4 <= '0; x6 <= '0;
            acc <= '0;
            valid_pipe <= '0;
        end else begin
            x2 <= qmul(x_in, x_in);
            x4 <= qmul(x2, x2);
            x6 <= qmul(x4, x2);
            acc <= ONE
                 - qmul(x2, HALF)
                 + qmul(x4, ONE_24TH)
                 - qmul(x6, ONE_720TH);
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = acc;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
