// eml_sqrt.v -- sqrt(x) in Q<WIDTH-FRAC>.<FRAC> fixed-point.
//
// Status: SCAFFOLD. Implements 3 Newton-Raphson iterations
// from initial guess x_in/2. Convergence is quadratic so 3
// iterations gives ~24 fractional bits of accuracy when
// x_in is in [0.25, 4]. Caller is responsible for argument
// scaling outside this range.
//
//   y_{k+1} = (y_k + x/y_k) / 2
//
// Pipeline: 4 stages (initial guess + 3 Newton steps).

`default_nettype none

module eml_sqrt #(
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

    function signed [WIDTH-1:0] qmul;
        input signed [WIDTH-1:0] a;
        input signed [WIDTH-1:0] b;
        reg signed [2*WIDTH-1:0] product;
        begin
            product = a * b;
            qmul = product >>> FRAC;
        end
    endfunction

    function signed [WIDTH-1:0] qdiv;
        input signed [WIDTH-1:0] a;
        input signed [WIDTH-1:0] b;
        reg signed [2*WIDTH-1:0] num;
        begin
            // (a << FRAC) / b
            num = $signed({a, {FRAC{1'b0}}});
            qdiv = (b == 0) ? '0 : num / b;
        end
    endfunction

    // y_n holds the current Newton iterate at stage n.
    reg signed [WIDTH-1:0] x_pipe1, x_pipe2, x_pipe3;
    reg signed [WIDTH-1:0] y0, y1, y2, y3;
    reg [PIPELINE_STAGES-1:0] valid_pipe;

    always @(posedge clk) begin
        if (rst) begin
            x_pipe1 <= '0; x_pipe2 <= '0; x_pipe3 <= '0;
            y0 <= '0; y1 <= '0; y2 <= '0; y3 <= '0;
            valid_pipe <= '0;
        end else begin
            // Stage 1: initial guess y0 = x/2 (cheap, biased high)
            x_pipe1 <= x_in;
            y0      <= x_in >>> 1;
            // Stage 2: y1 = (y0 + x/y0) / 2
            x_pipe2 <= x_pipe1;
            y1      <= (y0 + qdiv(x_pipe1, y0)) >>> 1;
            // Stage 3: y2 = (y1 + x/y1) / 2
            x_pipe3 <= x_pipe2;
            y2      <= (y1 + qdiv(x_pipe2, y1)) >>> 1;
            // Stage 4: y3 = (y2 + x/y2) / 2
            y3      <= (y2 + qdiv(x_pipe3, y2)) >>> 1;
            valid_pipe <= {valid_pipe[PIPELINE_STAGES-2:0], in_valid};
        end
    end

    assign result    = y3;
    assign out_valid = valid_pipe[PIPELINE_STAGES-1];

endmodule

`default_nettype wire
