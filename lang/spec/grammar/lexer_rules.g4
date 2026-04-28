// Token definitions for EML-lang.
// Imported by eml_lang.g4 in the canonical compiler.

lexer grammar lexer_rules;

// Keywords
MODULE      : 'module' ;
IMPORT      : 'import' ;
CONST       : 'const' ;
FN          : 'fn' ;
LET         : 'let' ;
WHERE       : 'where' ;
FORALL      : 'forall' ;
DOMAIN      : 'domain' ;
PRECISION   : 'precision' ;
CHAIN_ORDER : 'chain_order' ;
VERIFY      : '@verify' ;

// Type keywords
F64   : 'f64' ;
F32   : 'f32' ;
F16   : 'f16' ;
BF16  : 'bf16' ;
FIXED : 'fixed' ;

// Operators
PLUS    : '+' ;
MINUS   : '-' ;
STAR    : '*' ;
SLASH   : '/' ;
LE      : '<=' ;
LT      : '<'  ;
GE      : '>=' ;
GT      : '>'  ;
EQ      : '==' ;
NE      : '!=' ;
ASSIGN  : '=' ;
ARROW   : '->' ;
COLON   : ':' ;
SEMI    : ';' ;
COMMA   : ',' ;
DOT     : '.' ;
LPAREN  : '(' ;
RPAREN  : ')' ;
LBRACE  : '{' ;
RBRACE  : '}' ;
LBRACK  : '[' ;
RBRACK  : ']' ;

// Tokens
IDENT  : [a-zA-Z_][a-zA-Z0-9_]* ;
INT    : [0-9]+ ;
FLOAT  : [0-9]+ '.' [0-9]+ ([eE] [+-]? [0-9]+)? ;

// Whitespace + comments
LINE_COMMENT  : '//' ~[\r\n]* -> skip ;
BLOCK_COMMENT : '/*' .*? '*/' -> skip ;
WS            : [ \t\r\n]+    -> skip ;
