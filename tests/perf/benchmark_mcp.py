import argparse
import asyncio
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from statistics import median
from time import perf_counter

import chess
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

@asynccontextmanager
async def open_client():
    with tempfile.TemporaryDirectory(prefix='gambit-mcp-benchmark-',) as directory:
        config = Path(directory,) / 'config.toml'
        config.write_text('',)
        environment = {**os.environ, 'GAMBIT_RUNTIME_DIRECTORY': directory, 'GAMBIT_CONFIG': str(config,),}

        parameters = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'gambit.main',],
            env=environment,
        )

        with tempfile.TemporaryFile(mode='w+',) as errors:
            async with stdio_client(
                parameters,
                errlog=errors,
            ) as streams:
                async with ClientSession(
                    streams[0],
                    streams[1],
                ) as client:
                    await client.initialize()
                    yield client

def summarize_samples(samples,):
    ordered = sorted(samples,)

    return {
        'samples': len(samples,),
        'median_ms': round(
            median(samples,),
            2,
        ),
        'p95_ms': round(
            ordered[min(
                len(ordered,) - 1,
                int(len(ordered,) * 0.95,),
            )],
            2,
        ),
        'maximum_ms': round(
            max(samples,),
            2,
        ),
    }

async def run_benchmark(iterations: int,) -> dict:
    started = perf_counter()

    async with open_client() as client:
        connection_ms = (perf_counter() - started) * 1000
        board = chess.Board()
        positions = [board.fen(),]

        for notation in ('e4', 'e5', 'Nf3', 'Nc6', 'Bb5', 'a6'):
            board.push_san(notation,)
            positions.append(board.fen(),)

        samples = {'first': [], 'cached': [], 'facts_only': [], 'concurrent_cached': [],}
        sizes = []

        for fen in positions:
            for index in range(iterations + 1,):
                started = perf_counter()

                result = await client.call_tool(
                    'get_evidence',
                    {'fen': fen,},
                )

                samples['first' if index == 0 else 'cached'].append((perf_counter() - started) * 1000,)

                if result.is_error:
                    raise RuntimeError('Benchmark request failed.',)

                report = result.structured_content
                assert report['engine_evidence']['fen'] == report['position_reference']['fen']
                assert result.content == []
                sizes.append(len(json.dumps(report,).encode(),),)

            started = perf_counter()

            result = await client.call_tool(
                'get_evidence',
                {'fen': fen, 'sections': ['facts',],},
            )

            samples['facts_only'].append((perf_counter() - started) * 1000,)
            assert 'engine_evidence' not in result.structured_content

        async def cached_call():
            started = perf_counter()

            result = await client.call_tool(
                'get_evidence',
                {'fen': positions[0],},
            )

            assert not result.is_error

            return (perf_counter() - started) * 1000

        samples['concurrent_cached'] = await asyncio.gather(*(cached_call() for _ in range(8,)),)

        metrics = await client.call_tool(
            'get_metrics',
            {},
        )

        return {
            'transport': 'stdio',
            'connection_and_initialization_ms': round(
                connection_ms,
                2,
            ),
            'samples': {name: summarize_samples(values,) for name, values in samples.items()},
            'median_payload_bytes': median(sizes,),
            'median_token_estimate': round(median(sizes,) / 4,),
            'token_estimation_method': 'UTF-8 bytes divided by four; not a model tokenizer',
            'engine_searches': metrics.structured_content['search_count'],
            'scope': 'Local client-observed MCP round trips with seven fixed positions, no API calls, default search settings. First calls include engine startup as applicable. Excludes model generation, audio, and remote transport. Payload includes local facts and analysis; baseline tutoring included a first-ply observation instead of full features.',
        }

def main():
    parser = argparse.ArgumentParser(description='Measure local MCP evidence latency, concurrency, and structured response sizes.',)

    parser.add_argument(
        '--iterations',
        type=int,
        default=5,
    )

    arguments = parser.parse_args()

    if not 1 <= arguments.iterations <= 100:
        parser.error('Choose between 1 and 100 cached iterations.',)

    print(json.dumps(
        asyncio.run(run_benchmark(arguments.iterations,),),
        indent=4,
    ),)

if __name__ == '__main__':
    main()
