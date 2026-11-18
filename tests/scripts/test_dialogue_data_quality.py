from scripts.rl.dialogue_data_quality import audit,seed_texts


def test_seed_mock_and_fallback_rows_do_not_satisfy_real_data_gate():
    rows=[dict(player_text='seed',source='llm',relationship_delta=2)]*400
    rows += [dict(player_text='other',source='mock',relationship_delta=2)]*400
    rows += [dict(player_text='other',source='fallback',relationship_delta=2)]*400
    rows += [dict(player_text='private content',source='llm',relationship_delta=-1)]
    result=audit(rows,{'seed'})
    assert result['known_seed_rows']==400 and result['llm_rows_excluding_known_seeds']==1
    assert result['negative']==1 and not result['count_gate_met']
    assert 'private content' not in str(result)


def test_numeric_gate_does_not_automatically_approve_training_or_verify_provenance():
    seeds=seed_texts({'buckets':[{'text':'seed'},{'input':'another seed'}]})
    assert seeds=={'seed','another seed'}
    rows=[dict(player_text='unknown origin',source='llm',relationship_delta=1,request_id='logical')]*301
    result=audit(rows,seeds)
    assert result['count_gate_met']
    assert not result['provenance_verified'] and not result['training_approved']


def test_cli_reads_nested_jsonl_and_emits_only_aggregates(tmp_path,monkeypatch):
    import json
    from scripts.rl.dialogue_data_quality import main
    logs=tmp_path/'signals'/'nested'
    logs.mkdir(parents=True)
    (logs/'rows.jsonl').write_text(json.dumps(dict(source='llm',player_text='private text'))+'\n',encoding='utf-8')
    seeds=tmp_path/'seeds.json'
    seeds.write_text('[]',encoding='utf-8')
    output=tmp_path/'report.json'
    monkeypatch.setattr('sys.argv',['audit','--root',str(logs.parent),'--seeds',str(seeds),'--output',str(output)])
    main()
    result=output.read_text(encoding='utf-8')
    assert json.loads(result)['total']==1 and 'private text' not in result
