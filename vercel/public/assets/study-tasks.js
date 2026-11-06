// Study task instructions, shown in the task panel on BOTH pages: the dashboard
// (in either condition) and CLUE. This is the only copy of the text; edit it here.
//
// Keep it condition-neutral. Baseline participants see the same panel, so it must
// not mention CLUE, the simulator, or any tool only one condition has.
//
// **double asterisks** mark bold text; everything else is plain text.
//
// DRAFT: placeholder wording written from CLUE_Overview.md. Replace it with the
// final wording from the study playbook.

export const STUDY_TASKS = [
  {
    id: "task-1",
    label: "Task 1",
    title: "Metric Understanding",
    intro:
      "The dashboard reports **90-Day Customer Value** for the most recent acquisition month.",
    steps: [
      "Explain how 90-Day Customer Value is calculated, down to the data it is built from.",
      "Compared with the previous month, which component(s) drove the change in 90-Day Customer Value?",
    ],
    note: "Use any of the tools available to you. Say your reasoning aloud as you work.",
  },
  {
    id: "task-2",
    label: "Task 2",
    title: "Goal-Seeking",
    intro:
      "Leadership wants **90-Day Customer Value** to be **15% higher** than its current level.",
    steps: [
      "Propose at least one combination of Purchase Conversion Rate, Orders per Purchasing Customer, and Average Order Value that would reach this goal.",
      "For your proposal, describe what would need to change in the underlying data: purchasing customers, total orders, and total gross order value.",
      "Which proposal do you think is most realistic, and why?",
    ],
    note: "Use any of the tools available to you. Say your reasoning aloud as you work.",
  },
];
