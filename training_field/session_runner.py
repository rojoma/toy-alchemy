from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import asyncio, uuid
from dataclasses import dataclass
from typing import Optional
import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from .student_agent import StudentAgentFactory
from .teacher_agent import TeacherAgent
from .referee_agent import PrincipalAgent
from .evaluator import Evaluator, CostTracker
from .experiment_registry import ExperimentRegistry, ExperimentRecord
from .question_bank.question_bank import QuestionBank
from .proficiency_model import CurriculumGraph

console = Console()
PHASE_CONFIG = {
    'quick': [
        {'id':1,'name':'diagnosis','label':'Diagnosis','turns':2,'goal':'Find what student knows.'},
        {'id':2,'name':'exploration','label':'Exploration','turns':3,'goal':'Socratic questioning.'},
        {'id':3,'name':'practice','label':'Practice','turns':2,'goal':'Productive failure.'},
        {'id':4,'name':'reflection','label':'Reflection','turns':1,'goal':'Student summarizes.'},
    ],
    'standard': [
        {'id':1,'name':'diagnosis','label':'Diagnosis','turns':3,'goal':'Probe prior knowledge.'},
        {'id':2,'name':'exploration','label':'Exploration','turns':4,'goal':'Socratic dialogue.'},
        {'id':3,'name':'practice','label':'Practice','turns':4,'goal':'Guided practice.'},
        {'id':4,'name':'reflection','label':'Reflection','turns':1,'goal':'Metacognitive wrap-up.'},
    ],
    'deep': [
        {'id':1,'name':'diagnosis','label':'Diagnosis','turns':4,'goal':'Deep probe.'},
        {'id':2,'name':'exploration','label':'Exploration','turns':5,'goal':'Extended Socratic.'},
        {'id':3,'name':'practice','label':'Practice','turns':5,'goal':'Varied problems.'},
        {'id':4,'name':'reflection','label':'Reflection','turns':2,'goal':'Metacognitive reflection.'},
    ],
    # Live mode — no automatic turn cap. User explicitly ends via /api/live/{id}/end.
    'unlimited': [
        {'id':1,'name':'teaching','label':'Teaching','turns':9999,'goal':'Teach until the student is ready to end.'},
    ],
}
PHASE_STYLES = {1:'blue', 2:'yellow', 3:'magenta', 4:'green'}

@dataclass
class SessionConfig:
    student_id: str
    topic: str
    grade: int = 6
    subject: str = '算数'
    depth: str = 'standard'
    teaching_style: str = 'SOCRATIC'
    run_pre_test: bool = True
    run_post_test: bool = True
    question_style: str = 'nakatsu'
    hypothesis_id: Optional[str] = None
    teacher_id: str = 't001'

async def run_training_session(config: SessionConfig) -> dict:
    session_id = f'sess_{uuid.uuid4().hex[:8]}'
    console.rule(f'[bold]Session {session_id}[/bold]')
    student = StudentAgentFactory.from_profile(config.student_id)
    teacher = TeacherAgent.create_dr_owen()
    principal = PrincipalAgent()
    evaluator = Evaluator()
    registry = ExperimentRegistry()
    qbank = QuestionBank()
    curriculum = CurriculumGraph()
    cost_tracker = CostTracker()
    await qbank.init_db()
    ready, missing = curriculum.is_ready_to_learn(config.topic, student.proficiency_model.topic_proficiencies)
    if not ready:
        console.print(f'[yellow]Warning: missing prerequisites: {missing}[/yellow]')
    initial_proficiency = student.proficiency_model.topic_proficiencies.get(config.topic, student.proficiency_model.proficiency)
    turn_evaluations = []
    pre_test_score = None
    post_test_score = None
    pre_test_question_ids = []
    if config.run_pre_test:
        console.print('[cyan]Pre-test...[/cyan]')
        pre_questions = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5, config.question_style)
        pre_test_question_ids = [q.id for q in pre_questions]
        correct = 0
        for q in pre_questions:
            ans = await student.generate_test_answer(q.question_text, q.correct_answer, config.topic)
            if ans['is_correct']:
                correct += 1
        pre_test_score = round(correct / len(pre_questions) * 100)
        console.print(f'  Pre-test: {pre_test_score}/100')
    phases = PHASE_CONFIG[config.depth]
    total_turns = sum(p['turns'] for p in phases)
    last_student_text = None
    with Progress(SpinnerColumn(), TextColumn('[progress.description]{task.description}'), console=console) as progress:
        task = progress.add_task('Running...', total=total_turns)
        for phase in phases:
            lbl=phase['label']; gl=phase['goal']; console.print(Panel(f'[bold]{lbl}[/bold] -- {gl}', border_style=PHASE_STYLES.get(phase['id'], 'white')))
            for turn_num in range(1, phase['turns'] + 1):
                pid=phase['id']; plbl=phase['label']; pt=phase['turns']; progress.update(task, advance=1, description=f'Ph.{pid} {plbl} Turn {turn_num}/{pt}')
                current_prof = student.proficiency_model.topic_proficiencies.get(config.topic, student.proficiency_model.proficiency)
                teacher_result = await teacher.get_response(topic=config.topic, phase=phase['name'], phase_goal=phase['goal'], student_name=student.name_ja(), student_proficiency=current_prof, student_emotional=student.emotional_state.__dict__, student_last_response=last_student_text, grade=config.grade, subject=config.subject, turn_number=turn_num)
                teacher_text = teacher_result['text']
                console.print(f'[dark_orange]Dr. Owen:[/dark_orange] {teacher_text}')
                student_result = await student.get_response(teacher_message=teacher_text, topic=config.topic, phase=phase['name'])
                student_text = student_result['text']
                console.print(f'[steel_blue1]{student.name_ja()}:[/steel_blue1] {student_text}')
                turn_eval = await principal.evaluate_turn(teacher_text=teacher_text, student_text=student_text, topic=config.topic, phase=phase['name'], student_proficiency=current_prof, grade=config.grade, subject=config.subject)
                turn_evaluations.append(turn_eval)
                delta = max(0, turn_eval.understanding_delta)
                if delta > 0:
                    student.proficiency_model.update_after_session(config.topic, delta * 0.3)
                warn = (' HALLUC' if turn_eval.hallucination_detected else '') + (' DIRECT' if turn_eval.answer_given_directly else '')
                console.print(f'[dim]Referee: ZPD={turn_eval.zpd_alignment:.2f} Bloom=L{turn_eval.bloom_level}{warn}[/dim]')
                console.print(f'[dim]  -> {turn_eval.directive_to_teacher}[/dim]')
                last_student_text = student_text
    if config.run_post_test:
        console.print('[cyan]Post-test...[/cyan]')
        post_questions = await qbank.get_test_questions(config.grade, config.subject, config.topic, 5, config.question_style, exclude_ids=pre_test_question_ids)
        correct = 0
        for q in post_questions:
            ans = await student.generate_test_answer(q.question_text, q.correct_answer, config.topic)
            if ans['is_correct']:
                correct += 1
        post_test_score = round(correct / len(post_questions) * 100)
        console.print(f'  Post-test: {post_test_score}/100')
    final_proficiency = student.proficiency_model.topic_proficiencies.get(config.topic, 0)
    update_check = principal.check_skills_update_trigger()
    grade_result = principal.grade_session(post_test_score or 0)
    evaluation = evaluator.evaluate(session_id=session_id, turn_evaluations=turn_evaluations, pre_score=pre_test_score, post_score=post_test_score, student_id=config.student_id, teacher_id=config.teacher_id, topic=config.topic, grade=config.grade, subject=config.subject, depth=config.depth, initial_proficiency=initial_proficiency, final_proficiency=final_proficiency, cost_tracker=cost_tracker, principal_update_check=update_check)
    report_path = evaluator.generate_report(evaluation)
    record = ExperimentRecord(exp_id=session_id, hypothesis_id=config.hypothesis_id, timestamp=evaluation.timestamp, student_id=config.student_id, teacher_id=config.teacher_id, topic=config.topic, grade=config.grade, subject=config.subject, depth=config.depth, teaching_style=config.teaching_style, skills_used=teacher.config.selected_skills, pre_test_score=pre_test_score, post_test_score=post_test_score, learning_gain=evaluation.learning_gain, proficiency_delta=evaluation.proficiency_delta, hallucination_rate=evaluation.hallucination_rate, direct_answer_rate=evaluation.direct_answer_rate, avg_zpd_alignment=evaluation.avg_zpd_alignment, avg_bloom_level=evaluation.avg_bloom_level, frustration_events=evaluation.frustration_events, aha_moments=evaluation.aha_moments, teacher_compatibility_score=evaluation.teacher_compatibility_score, total_tokens=evaluation.total_tokens_used, cost_usd=evaluation.estimated_cost_usd, session_grade=grade_result['grade'])
    registry.register(record)
    console.rule('[bold green]Session Complete[/bold green]')
    gr=grade_result['grade']; gs=grade_result['status']; console.print(f'Grade: [bold]{gr}[/bold] ({gs})')
    console.print(f'Pre->Post: {pre_test_score} -> {post_test_score} (gain: +{evaluation.learning_gain})')
    console.print(f'Report: {report_path}')
    if update_check['trigger']:
        rec=update_check['recommendation']; console.print(f'[yellow]Skills update: {rec}[/yellow]')
    return {'session_id': session_id, 'evaluation': evaluation, 'report': str(report_path)}

async def run_batch(configs: list) -> list:
    results = []
    for cfg in configs:
        results.append(await run_training_session(cfg))
    return results

@click.command()
@click.option('--student', default='s001')
@click.option('--topic', default='速さ時間距離')
@click.option('--grade', default=6, type=int)
@click.option('--subject', default='算数')
@click.option('--depth', default='standard', type=click.Choice(['quick','standard','deep']))
@click.option('--style', default='nakatsu', type=click.Choice(['nakatsu','pisa']))
@click.option('--hypothesis', default=None)
@click.option('--no-test', is_flag=True)
@click.option('--batch-all-styles', is_flag=True)
def main(student, topic, grade, subject, depth, style, hypothesis, no_test, batch_all_styles):
    if batch_all_styles:
        configs = [SessionConfig(student_id=student, topic=topic, grade=grade, subject=subject, depth=d, question_style=style, hypothesis_id=hypothesis, run_pre_test=not no_test, run_post_test=not no_test) for d in ['quick','standard','deep']]
        asyncio.run(run_batch(configs))
    else:
        asyncio.run(run_training_session(SessionConfig(student_id=student, topic=topic, grade=grade, subject=subject, depth=depth, question_style=style, hypothesis_id=hypothesis, run_pre_test=not no_test, run_post_test=not no_test)))

if __name__ == '__main__':
    main()
