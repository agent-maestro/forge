// ANTLR4 grammar for EML-lang.
// Canonical reference: lang/spec/EML_LANG_DESIGN.md (Phase 1.1)
// Companion file: lexer_rules.g4

grammar EMLLang;

// ─── Top-level ────────────────────────────────────────────────

program
    : (typeDecl | constDecl | functionDecl)* EOF
    ;

// ─── Declarations ─────────────────────────────────────────────

typeDecl
    : 'type' ID '=' type
    ;

constDecl
    : 'const' ID ':' type '=' expr
    ;

functionDecl
    : annotation* 'fn' ID '(' params? ')' '->' type
       requiresClause* ensuresClause? block
    ;

params
    : param (',' param)*
    ;

param
    : ID ':' type
    ;

annotation
    : '@target' '(' targetSpec ')'
    | '@verify' '(' verifySpec ')'
    ;

targetSpec
    : ID (',' targetArg)*
    ;

targetArg
    : ID '=' (NUMBER | ID)
    ;

verifySpec
    : ID (',' ID '=' STRING)*
    ;

requiresClause
    : 'requires' expr
    ;

ensuresClause
    : 'ensures' expr
    ;

// ─── Types ────────────────────────────────────────────────────

type
    : 'Real'                                #RealType
    | 'Real' 'where' constraint             #ConstrainedType
    | 'f64' | 'f32' | 'f16' | 'bf16'       #FloatType
    | 'fixed' '<' INTEGER ',' INTEGER '>'   #FixedType
    | ID                                    #NamedType
    ;

constraint
    : 'chain_order' comparator INTEGER
    ;

comparator
    : '<=' | '>=' | '==' | '<' | '>' | '!='
    ;

// ─── Expressions ──────────────────────────────────────────────

block
    : '{' statement* expr '}'
    ;

statement
    : 'let' ID (':' type)? '=' expr  #LetStmt
    ;

// Operator precedence (highest first): unary, * /, + -, comparison
expr
    : '(' expr ')'                          #ParenExpr
    | builtin '(' argList? ')'              #BuiltinCall
    | ID '(' argList? ')'                   #FuncCall
    | '-' expr                              #UnaryNeg
    | expr op=('*'|'/') expr                #MulDiv
    | expr op=('+'|'-') expr                #AddSub
    | expr op=('<'|'>'|'<='|'>='|'=='|'!=') expr  #Compare
    | NUMBER                                #LiteralNum
    | ID                                    #VarRef
    ;

argList
    : expr (',' expr)*
    ;

builtin
    : 'exp' | 'ln' | 'sin' | 'cos' | 'tan'
    | 'sqrt' | 'pow' | 'eml' | 'abs' | 'clamp'
    | 'asin' | 'acos' | 'atan'
    | 'sinh' | 'cosh' | 'tanh'
    ;

// ─── Lexer ────────────────────────────────────────────────────

ID            : [a-zA-Z_][a-zA-Z0-9_]* ;
NUMBER        : INTEGER | FLOAT ;
INTEGER       : [0-9]+ ;
FLOAT         : [0-9]+ '.' [0-9]+ ([eE] [+-]? [0-9]+)? ;
STRING        : '"' (~["\\] | '\\' .)* '"' ;

LINE_COMMENT  : '//' ~[\r\n]* -> skip ;
BLOCK_COMMENT : '/*' .*? '*/' -> skip ;
WS            : [ \t\r\n]+    -> skip ;
