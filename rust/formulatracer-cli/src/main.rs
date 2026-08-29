use formulatracer_core::{
    canonical_json, execute_kernel, to_tex, CanonicalPolicy, Formula, SemanticDocument,
};
use std::{env, fs, process::ExitCode};

fn usage() -> ExitCode {
    eprintln!(
        "usage: formulatracer-native <canonicalize|tex|kernel> FILE | compare THEORY IMPLEMENTATION"
    );
    ExitCode::from(2)
}

fn read(path: &str) -> Result<SemanticDocument, String> {
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    SemanticDocument::from_json(&text).map_err(|e| e.to_string())
}

fn main() -> ExitCode {
    let args: Vec<_> = env::args().collect();
    let result: Result<String, String> = match args.get(1).map(String::as_str) {
        Some("canonicalize") if args.len() == 3 => read(&args[2]).and_then(|d| {
            canonical_json(&d.payload, CanonicalPolicy::default()).map_err(|e| e.to_string())
        }),
        Some("tex") if args.len() == 3 => read(&args[2]).map(|d| to_tex(&d.payload)),
        Some("kernel") if args.len() == 3 => fs::read_to_string(&args[2])
            .map_err(|e| e.to_string())
            .and_then(|text| serde_json::from_str(&text).map_err(|e| e.to_string()))
            .and_then(|request| execute_kernel(&request).map_err(|e| e.to_string()))
            .and_then(|result| serde_json::to_string_pretty(&result).map_err(|e| e.to_string())),
        Some("compare") if args.len() == 4 => read(&args[2]).and_then(|a| {
            read(&args[3]).map(|b| {
                Formula::from_document(a)
                    .verify_against(&Formula::from_document(b))
                    .status
            })
        }),
        _ => return usage(),
    };
    match result {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("UNRESOLVED: {error}");
            ExitCode::FAILURE
        }
    }
}
