"""
routes/scheduler.py — Auto-scheduler trigger, dreaming engine, and walk-forward simulation endpoints.
"""

import os
import json
import logging
from typing import Any
from flask import jsonify, request, Response
from .app import app, get_history_dir

logger = logging.getLogger(__name__)

@app.route("/api/trigger-schedule", methods=["POST", "GET"])
def trigger_schedule():
    """Manually trigger an automated scheduler run for testing."""
    try:
        from auto_scheduler import run_automated_analysis
        result = run_automated_analysis(run_name="Manual Test Trigger via API")
        if result:
            return jsonify({"status": "success", "message": "Automated schedule run executed successfully!", "data": result})
        return jsonify({"status": "error", "message": "Scheduler run returned no result"}), 500
    except Exception as e:
        logger.error(f"Manual trigger failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/dreaming/status", methods=["GET"])
def get_dreaming_status():
    """Return latest post-market dreaming consolidation report and macro axioms."""
    try:
        from pathlib import Path
        from dreaming_engine import get_dreaming_engine
        history_dir = get_history_dir()
        engine = get_dreaming_engine(history_dir)
        report_path = Path(history_dir) / "dream_report.json"
        latest_report = {}
        if report_path.exists():
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    latest_report = json.load(f)
            except Exception:
                pass

        return jsonify({
            "status": "ok",
            "data": {
                "total_axioms": len(engine._axioms),
                "macro_axioms": list(engine._axioms.values()),
                "latest_report": latest_report,
                "prompt_preview": engine.format_macro_axioms_prompt(max_axioms=3),
            }
        })
    except Exception as e:
        logger.error(f"/api/dreaming/status failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/dreaming/run", methods=["POST", "GET"])
def trigger_dreaming():
    """Trigger the 20:00 IST dreaming consolidation loop on demand."""
    try:
        from auto_scheduler import run_dreaming_consolidation
        report = run_dreaming_consolidation()
        if report:
            return jsonify({
                "status": "success",
                "message": "Dreaming consolidation completed successfully!",
                "data": report
            })
        return jsonify({"status": "error", "message": "Dreaming consolidation returned no report"}), 500
    except Exception as e:
        logger.error(f"Manual dreaming trigger failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




@app.route("/api/trajectories/export", methods=["GET", "POST"])
def export_trajectories():
    """
    Export trade reasoning trajectories for fine-tuning open-source LLMs.
    Supported formats: 'sharegpt', 'dpo', 'alpaca', or 'all' (default).
    """
    try:
        from trajectory_exporter import get_trajectory_exporter
        history_dir = get_history_dir()
        exporter = get_trajectory_exporter(history_dir)

        body = request.get_json(silent=True) or {}
        fmt = (body.get("format") or request.args.get("format", "all")).lower()
        inc_pend = bool(body.get("include_pending") or request.args.get("include_pending", "0").lower() in ("1", "true", "yes"))
        download = bool(body.get("download") or request.args.get("download", "0").lower() in ("1", "true", "yes"))

        def _jsonl_response(filename: str, records: list[dict[str, Any]]) -> Response:
            content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
            return Response(
                content,
                mimetype="application/x-jsonlines",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

        if fmt == "sharegpt":
            data = exporter.export_sharegpt(exporter.collect_trajectories(include_pending=inc_pend))
            if download:
                return _jsonl_response("trajectories_sharegpt.jsonl", data)
            return jsonify({"status": "ok", "format": "sharegpt", "count": len(data), "data": data})
        elif fmt == "dpo":
            data = exporter.export_dpo(exporter.collect_trajectories(include_pending=inc_pend))
            if download:
                return _jsonl_response("trajectories_dpo.jsonl", data)
            return jsonify({"status": "ok", "format": "dpo", "count": len(data), "data": data})
        elif fmt == "alpaca":
            data = exporter.export_alpaca(exporter.collect_trajectories(include_pending=inc_pend))
            if download:
                return _jsonl_response("trajectories_alpaca.jsonl", data)
            return jsonify({"status": "ok", "format": "alpaca", "count": len(data), "data": data})
        elif download or fmt == "jsonl":
            data = exporter.export_sharegpt(exporter.collect_trajectories(include_pending=inc_pend))
            return _jsonl_response("trajectories_sharegpt.jsonl", data)
        else:
            export_summary = exporter.export_all(include_pending=inc_pend)
            return jsonify({
                "status": "ok",
                "message": "Trajectories exported successfully to JSONL files!",
                "data": export_summary,
            })
    except Exception as e:
        logger.error(f"/api/trajectories/export failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/simulation/walk-forward", methods=["GET", "POST"])
def walk_forward_simulation_api():
    """
    Phase 6: Multi-Month Historical Walk-Forward Simulation API.
    Replays 6 months of historical sessions through 7 specialist dimensions,
    CogniGraph regimes, debate committees, and 3-tier scale-out engine.
    """
    try:
        from walk_forward_simulation import run_walk_forward_simulation
        history_dir = get_history_dir()
        report_file = os.path.join(history_dir, "walk_forward_simulation_report.json")

        force_run_param = str(request.args.get("force_run", "")).lower()
        force_run = force_run_param in ("1", "true", "yes")

        if request.method == "GET" and not force_run:
            if os.path.exists(report_file):
                try:
                    with open(report_file, "r", encoding="utf-8") as f:
                        cached_report = json.load(f)
                    return jsonify({"status": "ok", "data": cached_report, "cached": True})
                except Exception as e:
                    logger.warning(f"Failed to read walk-forward cache: {e}")

        # Extract parameters (from query params or JSON body)
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
        else:
            body = request.args

        try:
            months = int(float(str(body.get("months", 6)).strip()))
        except Exception:
            months = 6
        months = max(1, min(12, months))

        try:
            initial_capital = float(str(body.get("initial_capital", 100000.0)).replace(",", "").replace("₹", "").strip())
        except Exception:
            initial_capital = 100000.0
        initial_capital = max(1000.0, initial_capital)

        risk_profile = str(body.get("risk_profile") or "BALANCED").strip().upper()
        if risk_profile not in ("CONSERVATIVE", "AGGRESSIVE", "BALANCED"):
            risk_profile = "BALANCED"

        enable_cognigraph = str(body.get("enable_cognigraph", "true")).lower() not in ("false", "0", "no")
        enable_scale_out = str(body.get("enable_scale_out", "true")).lower() not in ("false", "0", "no")

        results = run_walk_forward_simulation(
            months=months,
            initial_capital=initial_capital,
            risk_profile=risk_profile,
            enable_cognigraph=enable_cognigraph,
            enable_scale_out=enable_scale_out,
            history_dir=history_dir,
        )
        return jsonify({"status": "ok", "data": results, "cached": False})
    except Exception as e:
        logger.error(f"/api/simulation/walk-forward failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


