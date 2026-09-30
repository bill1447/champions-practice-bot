                token=first.token,
                human_choice=PROTECT,
            )
            if first_result.terminal:
                raise SystemExit("ERROR: first self-KO turn ended battle too early")

            if coordinator.turn_state is not SealedTurnState.RESOLVED:
                raise SystemExit("ERROR: first self-KO turn did not resolve cleanly")

            ai_force = coordinator._ai_preseal_choices()
            if not any(choice.count("switch ") == 2 for choice in ai_force):
                raise SystemExit("ERROR: real session did not enter AI forced-switch phase")
            for choice in ai_force:
                switch_slots = [
                    command.strip().split()[1]
                    for command in choice.split(",")
                    if command.strip().startswith("switch ")
                ]
                if len(switch_slots) != len(set(switch_slots)):
                    raise SystemExit(
                        "ERROR: public pre-seal choices reused one bench slot twice: "
                        f"{choice}"
                    )
            human_wait = coordinator.human_legal_choices()
            wait_choice = "" if "" in human_wait else human_wait[0]

            forced = coordinator.lock_ai_action()
            forced_result = coordinator.commit_human_action(
                token=forced.token,
                human_choice=wait_choice,
            )
            if forced_result.terminal:
                raise SystemExit("ERROR: forced replacement incorrectly ended battle")

            final = coordinator.lock_ai_action()
            final_result = coordinator.commit_human_action(
                token=final.token,