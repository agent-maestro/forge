// ANTLR4 grammar for EML-lang.
// Status: SCAFFOLD. Token + production rules to be finalized as
// the spec stabilizes (lang/spec/SPEC.md).

grammar eml_lang;

// ─── Top-level ────────────────────────────────────────────────

program
    : moduleDecl? (importDecl | declaration)* EOF
    ;

moduleDecl  : 'module' IDENT ';' ;
importDecl  : 'import' qualifiedName ';' ;
qualifiedName : IDENT ('.' IDENT)* ;

// ─── Declarations ─────────────────────────────────────────────

declaration
    : constDecl
    | functionDecl
    | verifyBlock
    ;

constDecl
    : 'const' IDENT ':' type '=' expr ';'
    ;

functionDecl
    : 'fn' IDENT '(' paramList? ')' ('->' type)?
       whereClause? block
    ;

paramList   : param (',' param)* ;
param       : IDENT ':' type ;

whereClause
    : 'where' constraint (',' constraint)*
    ;
constraint
    : 'chain_order' ('<=' | '<' | '==') INT
    | 'domain' ':' expr
    | 'precision' ('<=' | '<') NUMBER
    ;

verifyBlock
    : '@verify' block
    ;

// ─── Types (preview) ──────────────────────────────────────────

type
    : 'f64' | 'f32' | 'f16' | 'bf16'
    | 'fixed' '<' INT ',' INT '>'
    | IDENT
    ;

// ─── Statements / expressions ─────────────────────────────────

block       : '{' stmt* '}' ;
stmt
    : letStmt
    | exprStmt
    | returnStmt
    ;

letStmt     : 'let' IDENT (':' type)? '=' expr ';' ;
exprStmt    : expr ';' ;
returnStmt  : expr ;  // last expression in block is return

expr
    : expr op=('*'|'/') expr   #BinaryMulDiv
    | expr op=('+'|'-') expr   #BinaryAddSub
    | expr op=('<'|'>'|'<='|'>='|'=='|'!=') expr  #Compare
    | 'forall' IDENT ':' type 'where' expr block  #Quantifier
    | IDENT '(' argList? ')'   #Call
    | '(' expr ')'             #Paren
    | NUMBER                   #Literal
    | IDENT                    #Var
    ;

argList     : expr (',' expr)* ;

// ─── Lexer ────────────────────────────────────────────────────

IDENT       : [a-zA-Z_][a-zA-Z0-9_]* ;
NUMBER      : INT | FLOAT ;
INT         : [0-9]+ ;
FLOAT       : [0-9]+ '.' [0-9]+ ([eE] [+-]? [0-9]+)? ;

LINE_COMMENT  : '//' ~[\r\n]* -> skip ;
BLOCK_COMMENT : '/*' .*? '*/' -> skip ;
WS            : [ \t\r\n]+    -> skip ;
