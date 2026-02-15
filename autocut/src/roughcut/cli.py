"""CLI entry point using Typer."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from roughcut.constants import LOG_FORMAT
from roughcut.pipeline import run_pipeline, run_review

app = typer.Typer(
    name="roughcut",
    help="Automatic video rough cut generator with Premiere XML export.",
)


@app.command("run")
def run_cmd(
    input: Path = typer.Option(..., "--input", "-i", help="Input directory containing media files"),
    profile: Path = typer.Option(..., "--profile", "-p", help="Path to YAML profile config"),
    output: Path = typer.Option(..., "--output", "-o", help="Output directory"),
    seed: int | None = typer.Option(None, "--seed", "-s", help="Random seed for reproducibility"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only generate reports, skip rendering"),
    fast_preview: bool = typer.Option(False, "--fast-preview", help="Render 720p preview (faster)"),
    max_workers: int = typer.Option(1, "--max-workers", "-w", help="Number of parallel workers"),
    favorites: Path | None = typer.Option(None, "--favorites", help="Path to favorites.txt (force include)"),
    exclude: Path | None = typer.Option(None, "--exclude", help="Path to exclude.txt (force exclude)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Run the roughcut pipeline on a media directory."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT)

    # Validate inputs
    if not input.exists():
        typer.echo(f"Error: Input directory does not exist: {input}", err=True)
        raise typer.Exit(1)

    if not profile.exists():
        typer.echo(f"Error: Profile file does not exist: {profile}", err=True)
        raise typer.Exit(1)

    output.mkdir(parents=True, exist_ok=True)

    typer.echo("Roughcut - Automatic Video Editor")
    typer.echo(f"  Input:   {input}")
    typer.echo(f"  Profile: {profile}")
    typer.echo(f"  Output:  {output}")
    if dry_run:
        typer.echo("  Mode:    DRY RUN (no rendering)")
    elif fast_preview:
        typer.echo("  Mode:    FAST PREVIEW (720p)")
    typer.echo()

    run_pipeline(
        input_dir=input,
        profile_path=profile,
        output_dir=output,
        seed=seed,
        dry_run=dry_run,
        fast_preview=fast_preview,
        max_workers=max_workers,
        favorites_path=favorites,
        exclude_path=exclude,
    )

    typer.echo("\nDone!")


@app.command("review")
def review_cmd(
    input: Path = typer.Option(..., "--input", "-i", help="Input directory containing media files"),
    profile: Path = typer.Option(..., "--profile", "-p", help="Path to YAML profile config"),
    output: Path = typer.Option(..., "--output", "-o", help="Output directory for candidate list"),
    max_workers: int = typer.Option(1, "--max-workers", "-w", help="Number of parallel workers"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Analyze media and output candidate list for manual review.

    Generates candidates.csv with all scored shots, allowing you to
    create favorites.txt and exclude.txt before running the full pipeline.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT)

    if not input.exists():
        typer.echo(f"Error: Input directory does not exist: {input}", err=True)
        raise typer.Exit(1)

    if not profile.exists():
        typer.echo(f"Error: Profile file does not exist: {profile}", err=True)
        raise typer.Exit(1)

    output.mkdir(parents=True, exist_ok=True)

    typer.echo("Roughcut - Review Mode")
    typer.echo(f"  Input:   {input}")
    typer.echo(f"  Output:  {output}")
    typer.echo()

    run_review(
        input_dir=input,
        profile_path=profile,
        output_dir=output,
        max_workers=max_workers,
    )

    typer.echo("\nReview complete! Check the output directory for candidate files.")
    typer.echo("  - candidates.csv: All scored shots")
    typer.echo("  - favorites_template.txt: Copy and edit to create favorites.txt")
    typer.echo("  - exclude_template.txt: Copy and edit to create exclude.txt")


@app.command("version")
def version_cmd() -> None:
    """Show version information."""
    from roughcut import __version__
    typer.echo(f"roughcut {__version__}")


if __name__ == "__main__":
    app()
