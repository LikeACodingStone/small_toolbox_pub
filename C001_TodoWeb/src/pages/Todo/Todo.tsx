import React from "react";
import { motion } from "framer-motion";
import "./Todo.css";
import {
  DatabaseView,
  TodoDatabaseProvider,
  TodoSyncBar,
} from "./TodoDatabase";

const formatTodayEn = (date: Date) => {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const week =
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getDay()] || "";
  return `${yyyy}-${mm}-${dd} ${week}`;
};

interface TodoProps {
  onLock: () => void;
}

const Todo: React.FC<TodoProps> = ({ onLock }) => {
  const todayLabel = formatTodayEn(new Date());

  return (
    <motion.div
      className="todo-page"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <TodoDatabaseProvider>
        <TodoSyncBar onLock={onLock} />
        <div className="top-grid">
          <DatabaseView
            view={{
              id: "wish",
              title: "Reminder: the most important items:",
              mode: "wish",
              barClass: "section-bar-reminder",
              dimOnHover: true,
            }}
          />
          <DatabaseView
            view={{
              id: "board-high",
              title: (
                <>
                  <span className="section-title-strong">Execution: TODO</span>(
                  <span className="title-date-highlight">{todayLabel}</span>):
                </>
              ),
              mode: "board",
              priority: "high",
            }}
          />
        </div>

        <div className="mid-grid">
          <DatabaseView
            view={{
              id: "week",
              title: "This Week:",
              mode: "week",
              barClass: "section-bar-schedule",
            }}
          />
          <DatabaseView
            view={{
              id: "month",
              title: "This Month:",
              mode: "month",
              barClass: "section-bar-schedule",
            }}
          />
        </div>

        <div className="bottom-grid">
          <DatabaseView
            view={{
              id: "year",
              title: "This Year:",
              mode: "year",
              barClass: "section-bar-schedule",
            }}
          />
          <DatabaseView
            view={{
              id: "delay",
              title: "Overdue Tasks:",
              mode: "delay",
              barClass: "section-bar-gold",
              dimOnHover: true,
            }}
          />
        </div>
      </TodoDatabaseProvider>
    </motion.div>
  );
};

export default Todo;
