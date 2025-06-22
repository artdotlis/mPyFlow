import logging
import multiprocessing

import sys
import time

import threading
import traceback
from datetime import datetime
from mpyflow.library.worker import Worker
from mpyflow.shared.container.factory import ProcessCon
from mpyflow.shared.errors.exception import KnownException, BootstrapEx
from mpyflow.shared.interfaces.logger import SyncStdoutInterface
from mpyflow.shared.interfaces.work import WorkableTermInterface
from mpyflow.shared.logger.manager import factory_sync_out, factory_log_manager
from mpyflow.shared.logger.redirect import RedirectSysHandler
from multiprocessing.context import SpawnContext, SpawnProcess
from pathlib import Path
from threading import Thread
from typing import Iterable, Any, Sequence

type _MPC = multiprocessing.context.SpawnProcess


def _local_check(
    sync_out_pr: SyncStdoutInterface, pr_list: tuple[_MPC, ...], /
) -> Iterable[int]:
    for pr_elem in pr_list:
        if not sync_out_pr.error_occurred():
            pr_elem.join(2)

        if not pr_elem.is_alive():
            yield 1


def _wait_to_close(
    loop_cnt_canceled: int,
    worker_pr: tuple[_MPC, ...],
    sync_out_pr: SyncStdoutInterface,
    /,
) -> int:
    to_close = True
    loop_in = loop_cnt_canceled
    while to_close:
        cnt = sum(_local_check(sync_out_pr, worker_pr))
        if cnt == len(worker_pr):
            to_close = False

        if sync_out_pr.error_occurred():
            loop_in += 1
            time.sleep(1)

        if loop_in >= 300:
            to_close = False
    return loop_in


def _await_processes(
    workable_dict: tuple[WorkableTermInterface, ...],
    worker_pr: tuple[_MPC, ...],
    extra_pr: tuple[_MPC, ...],
    sync_out_structure: SyncStdoutInterface,
    sync_out_pr: SyncStdoutInterface,
    std_buffer: RedirectSysHandler,
    /,
) -> None:
    loop_cnt_canceled = 0
    if not sync_out_structure.error_occurred():
        for pr_elem in worker_pr:
            pr_elem.start()

        loop_cnt_canceled = _wait_to_close(loop_cnt_canceled, worker_pr, sync_out_pr)
        if loop_cnt_canceled >= 300 and sync_out_pr.error_occurred():
            for pr_elem in worker_pr:
                pr_elem.terminate()
            _workable_on_terminate(workable_dict)
            for pr_elem in extra_pr:
                pr_elem.terminate()
    std_buffer.join_errors()
    if loop_cnt_canceled < 300:
        logs: Sequence[Thread | SpawnProcess] = (
            _close_logger(sync_out_pr),
            _close_logger(sync_out_structure),
            *extra_pr,
        )
        for log_elem in logs:
            log_elem.join()
    std_buffer.close()
    if loop_cnt_canceled >= 300:
        buf = "\n\n\n{'#' * 10}\n\n\n"
        print(f"{buf}WARNING! WARNING! PROCESSES WERE TERMINATED!{buf}")


def _close_logger(sync_out: SyncStdoutInterface, /) -> threading.Thread:
    sync_out.flush_log_stats()
    sync_out.flush_stats()
    thread_logger_cl = threading.Thread(target=sync_out.close_logger)
    thread_logger_cl.daemon = False
    thread_logger_cl.start()
    return thread_logger_cl


def _workable_on_error[IT, OT](workables: tuple[WorkableTermInterface, ...], /) -> None:
    for workable_elem in workables:
        workable_elem.workable_set_error()


def _workable_on_terminate[
    IT, OT
](workables: tuple[WorkableTermInterface, ...], /) -> None:
    for workable_elem in workables:
        workable_elem.terminated_set_error()


def _factory_sync_out(
    step_name: str,
    wdl: Path,
    work: tuple[WorkableTermInterface, ...],
    ctx: SpawnContext,
    /,
) -> tuple[SyncStdoutInterface, SyncStdoutInterface, ProcessCon]:
    log_man = factory_log_manager(ctx)
    proc_con: ProcessCon = ProcessCon(log_manager=log_man, workable=work)
    procs, sout_struc = factory_sync_out(wdl, "structure_creating_process", log_man, ctx)
    proc_con.add_new_procs(procs)
    procs, sync_out = factory_sync_out(wdl, step_name, log_man, ctx)
    proc_con.add_new_procs(procs)
    for proc in proc_con.extra_process:
        proc.start()
    return sout_struc, sync_out, proc_con


def _create_and_start_worker(
    workers: tuple[tuple[int, Worker[Any, Any]], ...],
    id_name: str,
    build_out: SyncStdoutInterface,
    sync_out: SyncStdoutInterface,
    ctx: multiprocessing.context.SpawnContext,
    /,
) -> Iterable[multiprocessing.context.SpawnProcess]:
    ind = 0
    all_cnt = sum(cnt for cnt, _ in workers)
    for cnt, work in workers:
        for _ in range(cnt):
            work.register_worker(sync_out)
            ind += 1
            proc = ctx.Process(target=work.run, name=f"worker-{ind}")
            msg = f"Started worker process {ind} / {all_cnt}"
            build_out.print_message(id_name, msg, 1.0 * ind / all_cnt, False)
            yield proc


def start_worker(
    working_dir_log: Path,
    step_name: str,
    factory_ctx: multiprocessing.context.SpawnContext,
    workers: tuple[tuple[int, Worker[Any, Any]], ...],
    workables: tuple[WorkableTermInterface, ...],
    /,
) -> None:
    working_dir_log = working_dir_log.joinpath(
        f"log_{datetime.now().strftime('%d_%m_%Y__%H_%M_%S')}"
    )
    sout_struc, sync_out, proc_con = _factory_sync_out(
        step_name, working_dir_log, workables, factory_ctx
    )
    id_name = "factory_worker"
    handlers = RedirectSysHandler(sout_struc, sys.__stdout__, sys.__stderr__)
    handlers.set_sys_handler()
    try:
        msg = "Checking workers count"
        sout_struc.print_message(id_name, msg, 0.0, False)
        no_err = True
        for cnt, _ in workers:
            if cnt < 1:
                no_err = False
                break
        if no_err:
            proc_con.add_new_workers(
                _create_and_start_worker(
                    workers, id_name, sout_struc, sync_out, factory_ctx
                )
            )
    except KnownException as known:
        sout_struc.print_logger(
            f"Expected error: {known!s} in {id_name}\n{traceback.format_exc()}",
            logging.ERROR,
        )
        handlers.on_known_errors(str(known))
        _workable_on_error(proc_con.workable)
    except Exception as error:
        sout_struc.print_logger(
            f"Not expected error: {error!s} in {id_name}\n{traceback.format_exc()}",
            logging.ERROR,
        )
        _workable_on_error(proc_con.workable)
        handlers.on_exception(str(error))
        raise
    else:
        if no_err:
            msg = r"All Worker creation \[done]!"
            sout_struc.print_message(id_name, msg, 100.0, True)
            sout_struc.print_logger("All Worker started", logging.INFO)
        else:
            kn_err = BootstrapEx("Worker count should be set at least to one")
            sout_struc.print_logger(
                f"Expected error: {kn_err!s} in {id_name}\n{traceback.format_exc()}",
                logging.ERROR,
            )
            handlers.on_known_errors(str(kn_err))
            _workable_on_error(proc_con.workable)
    finally:
        _await_processes(
            proc_con.workable,
            proc_con.worker_process,
            proc_con.extra_process,
            sout_struc,
            sync_out,
            handlers,
        )
