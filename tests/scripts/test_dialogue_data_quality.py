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


def test_natural_gate_requires_complete_scoped_attribution_and_deduplicates():
    identity=dict(game_id='aesir',player_id='p',save_id='s',companion_id='npc',run_id='r',request_id='one')
    base=dict(**identity,player_text='private',source='llm',relationship_delta=1,
        data_origin='natural',origin_authority='server_configuration',turn_complete=True)
    rows=[base,dict(base),dict(base,data_origin='seed',request_id='two'),
          dict(base,data_origin='fault',request_id='three'),dict(base,request_id='four',turn_complete=False),
          dict(base,request_id='five',origin_authority='client'),dict(base,request_id='six',player_text='known seed')]
    result=audit(rows,{'known seed'})
    assert result['attributed_natural_unique_complete_llm']==1
    assert not result['natural_count_gate_met'] and not result['training_approved']
    assert result['quality_by_origin']['seed']['rows']==1
    assert result['quality_by_origin']['fault']['rows']==1
    assert result['quality_by_origin']['unknown']['rows']==1
    assert 'private' not in str(result)
